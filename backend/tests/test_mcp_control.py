import asyncio
import json
import re
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from test_projects import Services as ProjectServices
from test_projects import client_for as project_client_for
from test_projects import sentence as project_sentence
from test_projects import snapshot as project_snapshot
from test_projects import speech_request as project_speech_request
from test_speech_jobs import FakeSpeech

from shadowing_video_studio.control import ApplicationControl
from shadowing_video_studio.control_api import router as control_router
from shadowing_video_studio.mcp_control import (
    LocalMcpAccess,
    McpSettings,
    create_mcp,
)
from shadowing_video_studio.speech import VOICE, HeavyJobGate, SpeechSentence
from shadowing_video_studio.speech_assets import SpeechAssets
from shadowing_video_studio.speech_jobs import SpeechJobs

READ_TOKEN = "read-token-for-local-mcp-tests-123456789"
EXECUTE_TOKEN = "execute-token-for-local-mcp-tests-123456789"


def result_data(result):
    if result.structuredContent is not None:
        return result.structuredContent
    return json.loads(result.content[0].text)


class FakeVideo:
    async def readiness(self):
        return {"available": True, "reason": None}

    async def submit(self, *_args, **_kwargs):
        raise AssertionError("This integration scenario submits speech only.")

    def get(self, _job_id):
        raise AssertionError("This integration scenario queries a speech job only.")


class FakeVisuals:
    library = None

    def readiness(self):
        return {"available": False, "reason": "Synthetic fixture."}


def make_app(tmp_path, settings=None, project_services=None):
    if project_services is None:
        speech = SpeechJobs(FakeSpeech(), SpeechAssets(tmp_path), HeavyJobGate())
        video = FakeVideo()
    else:
        speech = project_services.speech
        video = project_services.video
    application = FastAPI()
    application.state.speech = speech
    application.state.video = video
    application.state.visuals = FakeVisuals()
    if project_services is not None:
        application.state.projects = project_services.projects
    application.state.control = ApplicationControl(speech, video)
    application.state.mcp_settings = settings or McpSettings(READ_TOKEN, EXECUTE_TOKEN)
    application.state.mcp = create_mcp(application)
    application.mount(
        "/mcp",
        LocalMcpAccess(application.state.mcp.streamable_http_app(), application),
    )
    application.include_router(control_router)
    return application, speech


@asynccontextmanager
async def mcp_session(application, token):
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), headers=headers
    ) as client:
        async with streamable_http_client(
            "http://127.0.0.1:8000/mcp/",
            http_client=client,
            terminate_on_close=False,
        ) as (read_stream, write_stream, _get_session_id):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                yield session


def test_mcp_streamable_http_discovery_review_execution_and_shared_job(tmp_path):
    async def scenario():
        application, speech = make_app(tmp_path)
        mcp = application.state.mcp
        async with mcp.session_manager.run():
            async with mcp_session(application, READ_TOKEN) as read_client:
                listed = await read_client.list_tools()
                names = {tool.name for tool in listed.tools}
                assert {
                    "get_capabilities",
                    "list_text_providers",
                    "list_visual_assets",
                    "request_generation",
                    "get_request",
                    "execute_request",
                    "get_job",
                } <= names
                assert "approve_request" not in names and "decide_review" not in names

                capabilities = await read_client.call_tool("get_capabilities", {})
                assert not capabilities.isError
                capabilities_data = result_data(capabilities)
                assert capabilities_data["access"] == "read"
                assert capabilities_data["deferred"]["projects"] == "Task008"

                denied = await read_client.call_tool(
                    "request_generation",
                    {
                        "request": {
                            "requestId": "readonly-request",
                            "operation": "speech",
                            "payload": {"sentences": [{"id": "one", "text": "Read only attempt."}]},
                        }
                    },
                )
                assert denied.isError
                assert result_data(denied)["error"]["code"] == "forbidden"
                assert application.state.control.list_reviews() == []

                malformed = await read_client.call_tool(
                    "request_generation",
                    {
                        "request": {
                            "requestId": "invalid-source",
                            "operation": "speech",
                            "payload": {
                                "sentences": [
                                    {
                                        "id": "one",
                                        "text": "PRIVATE DIALOGUE MUST NEVER ECHO",
                                        "privatePath": "/Users/private/source.txt",
                                    }
                                ]
                            },
                        }
                    },
                )
                assert malformed.isError
                assert "PRIVATE DIALOGUE MUST NEVER ECHO" not in str(malformed)
                assert "/Users/private/source.txt" not in str(malformed)

            source_text = "The MCP request should be reviewed in the browser."
            async with mcp_session(application, EXECUTE_TOKEN) as execute_client:
                accepted = await execute_client.call_tool(
                    "request_generation",
                    {
                        "request": {
                            "requestId": "shared-request",
                            "operation": "speech",
                            "payload": {"sentences": [{"id": "one", "text": source_text}]},
                        }
                    },
                )
                assert not accepted.isError
                request = result_data(accepted)
                assert request["state"] == "needs_review"
                assert request["reviewPath"] == "/control/shared-request"
                assert "nonce" not in request and "payload" not in request
                assert "PRIVATE" not in str(request)

                repeated = await execute_client.call_tool(
                    "request_generation",
                    {
                        "request": {
                            "requestId": "shared-request",
                            "operation": "speech",
                            "payload": {"sentences": [{"id": "one", "text": source_text}]},
                        }
                    },
                )
                assert not repeated.isError
                assert result_data(repeated) == request

                before_approval = await execute_client.call_tool(
                    "execute_request", {"request_id": "shared-request"}
                )
                assert before_approval.isError
                assert result_data(before_approval)["error"]["code"] == "review_required"

                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=application),
                    base_url="http://127.0.0.1:8000",
                ) as browser:
                    review_page = await browser.get("/control/shared-request")
                    assert review_page.status_code == 200
                    assert source_text in review_page.text
                    nonce_match = re.search(
                        r'name="nonce" value="([A-Za-z0-9_-]+)"', review_page.text
                    )
                    assert nonce_match
                    approval = await browser.post(
                        "/control/shared-request/decision",
                        data={"nonce": nonce_match.group(1), "decision": "approve"},
                    )
                    assert approval.status_code == 303

                queried = await execute_client.call_tool(
                    "get_request", {"request_id": "shared-request"}
                )
                assert not queried.isError
                queried_data = result_data(queried)
                assert queried_data["state"] == "approved"
                assert "nonce" not in queried_data
                assert "payload" not in queried_data

                submitted = await execute_client.call_tool(
                    "execute_request", {"request_id": "shared-request"}
                )
                assert not submitted.isError
                submitted_data = result_data(submitted)
                job = submitted_data["result"]
                assert job["id"]
                assert submitted_data["state"] == "submitted"
                await speech.wait()

                repeated_submission = await execute_client.call_tool(
                    "execute_request", {"request_id": "shared-request"}
                )
                assert not repeated_submission.isError
                assert result_data(repeated_submission) == submitted_data

            async with mcp_session(application, READ_TOKEN) as read_client:
                job_result = await read_client.call_tool(
                    "get_job", {"kind": "speech", "job_id": job["id"]}
                )
                assert not job_result.isError
                job_data = result_data(job_result)
                assert job_data["status"] == "completed"
                assert job_data["sentences"][0]["text"] == source_text
                assert len(speech.provider.calls) == 1
        await application.state.control.close()
        await speech.close()

    asyncio.run(scenario())


def test_mcp_access_gate_blocks_disabled_unauthorized_and_remote_requests(tmp_path):
    async def scenario():
        application, speech = make_app(tmp_path, McpSettings())
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://127.0.0.1:8000",
        ) as client:
            disabled = await client.get("/mcp/")
            assert disabled.status_code == 404

        application.state.mcp_settings = McpSettings(READ_TOKEN, EXECUTE_TOKEN)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://127.0.0.1:8000",
        ) as client:
            unauthorized = await client.get("/mcp/")
            assert unauthorized.status_code == 401
            assert unauthorized.headers["www-authenticate"] == "Bearer"

            for headers in (
                {
                    "Authorization": f"Bearer {EXECUTE_TOKEN}",
                    "Host": "rebound.example",
                },
                {
                    "Authorization": f"Bearer {EXECUTE_TOKEN}",
                    "Origin": "https://foreign.example",
                },
            ):
                rejected = await client.get("/mcp/", headers=headers)
                assert rejected.status_code == 403
        await application.state.control.close()
        await speech.close()

    asyncio.run(scenario())


def test_mcp_transient_speech_uses_project_store_assets_without_binding_saved_project(tmp_path):
    async def scenario():
        original_services = ProjectServices(tmp_path)
        saved_snapshot = project_snapshot(
            [project_sentence("sentence-001", "Saved project dialogue.")],
            source_text="Saved original source.",
        )
        saved = original_services.store.create("Saved practice", saved_snapshot, "1" * 32)
        async with project_client_for(original_services) as project_ui:
            saved_job_response = await project_ui.post(
                f"/api/projects/{saved['id']}/speech",
                json=project_speech_request(
                    saved_snapshot, "2" * 32, project_name="Saved practice", revision=1
                ),
            )
            assert saved_job_response.status_code == 202, saved_job_response.text
            await original_services.speech.wait()
            saved_job_id = saved_job_response.json()["id"]
            assert original_services.speech.get(saved_job_id)["status"] == "completed"
        saved_job = original_services.speech.get(saved_job_id)
        saved_audio_id = saved_job["sentences"][0]["assetId"]
        assert original_services.store.speech_asset(saved_audio_id) is not None
        assert [item["id"] for item in original_services.store.attempts(saved["id"])] == [
            saved_job_id
        ]
        await original_services.video.close()
        await original_services.speech.close()

        # A fresh service can resolve the saved job through Task008's durable store.
        project_services = ProjectServices(tmp_path)
        before = project_services.store.get(saved["id"])
        assert before["revision"] == 1
        before_attempts = project_services.store.attempts(saved["id"])
        assert [item["id"] for item in before_attempts] == [saved_job_id]
        assert project_services.speech.get(saved_job_id)["status"] == "completed"

        application, speech = make_app(tmp_path, project_services=project_services)
        assert speech is project_services.speech
        assert speech.assets is project_services.assets
        assert speech.assets.store is project_services.store
        assert application.state.control.speech is speech
        assert application.state.control.video is project_services.video
        assert application.state.video.speech is speech
        assert application.state.video.gate is speech.gate

        mcp = application.state.mcp
        text = "Transient MCP dialogue remains separate from the saved project."
        async with mcp.session_manager.run():
            async with mcp_session(application, READ_TOKEN) as reader:
                hidden_saved_job = await reader.call_tool(
                    "get_job", {"kind": "speech", "job_id": saved_job_id}
                )
                assert hidden_saved_job.isError
                assert result_data(hidden_saved_job)["error"]["code"] == "not_found"
                assert result_data(hidden_saved_job)["error"]["statusCode"] == 404

            async with mcp_session(application, EXECUTE_TOKEN) as execute_client:
                accepted = await execute_client.call_tool(
                    "request_generation",
                    {
                        "request": {
                            "requestId": "unbound-transient-request",
                            "operation": "speech",
                            "payload": {"sentences": [{"id": "transient-1", "text": text}]},
                        }
                    },
                )
                assert not accepted.isError
                request = result_data(accepted)
                assert request["state"] == "needs_review"
                assert "projectId" not in request and "projectRevision" not in request

                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=application),
                    base_url="http://127.0.0.1:8000",
                ) as browser:
                    review_page = await browser.get(request["reviewPath"])
                    nonce_match = re.search(
                        r'name="nonce" value="([A-Za-z0-9_-]+)"', review_page.text
                    )
                    assert review_page.status_code == 200 and nonce_match
                    approved = await browser.post(
                        f"{request['reviewPath']}/decision",
                        data={"nonce": nonce_match.group(1), "decision": "approve"},
                    )
                    assert approved.status_code == 303

                submitted = await execute_client.call_tool(
                    "execute_request", {"request_id": request["requestId"]}
                )
                assert not submitted.isError
                result = result_data(submitted)
                assert result["state"] == "submitted"
                job_id = result["result"]["id"]
                assert "projectId" not in result["result"]
                assert "projectRevision" not in result["result"]
                await speech.wait()

            async with mcp_session(application, READ_TOKEN) as reader:
                completed = await reader.call_tool("get_job", {"kind": "speech", "job_id": job_id})
                assert not completed.isError
                job = result_data(completed)
                assert job["status"] == "completed"
                assert job["sentences"][0]["text"] == text
                assert "projectId" not in job and "projectRevision" not in job

        asset_id = job["sentences"][0]["assetId"]
        asset = speech.assets.match(
            asset_id,
            SpeechSentence("transient-1", text),
            project_services.provider.fingerprint_for_voice(VOICE),
            VOICE,
        )
        assert asset.project_id is None and asset.document_id is None
        assert project_services.store.speech_asset(asset_id) is None
        after_attempts = project_services.store.attempts(saved["id"])
        assert after_attempts == before_attempts
        after = project_services.store.get(saved["id"])
        assert after["revision"] == before["revision"]
        assert after["snapshot"] == before["snapshot"]
        assert len(project_services.provider.calls) == 1
        saved_asset = project_services.assets.match(
            saved_audio_id,
            SpeechSentence("sentence-001", "Saved project dialogue."),
            project_services.provider.fingerprint_for_voice(VOICE),
            VOICE,
            saved["id"],
            saved_snapshot["documentId"],
        )
        assert saved_asset.project_id == saved["id"]
        assert not speech.gate.busy
        await application.state.control.close()
        await speech.close()
        await project_services.video.close()

    asyncio.run(scenario())
