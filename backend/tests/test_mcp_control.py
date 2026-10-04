import asyncio
import json
import re
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from test_speech_jobs import FakeSpeech

from shadowing_video_studio.control import ApplicationControl
from shadowing_video_studio.control_api import router as control_router
from shadowing_video_studio.mcp_control import (
    LocalMcpAccess,
    McpSettings,
    create_mcp,
)
from shadowing_video_studio.speech import HeavyJobGate
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


def make_app(tmp_path, settings=None):
    speech = SpeechJobs(FakeSpeech(), SpeechAssets(tmp_path), HeavyJobGate())
    video = FakeVideo()
    application = FastAPI()
    application.state.speech = speech
    application.state.video = video
    application.state.visuals = FakeVisuals()
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
