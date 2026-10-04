import asyncio

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError
from test_speech_jobs import FakeSpeech

from shadowing_video_studio.control import (
    ApplicationControl,
    ControlError,
    GenerationRequest,
)
from shadowing_video_studio.control_api import router as control_router
from shadowing_video_studio.speech import HeavyJobGate
from shadowing_video_studio.speech_assets import SpeechAssets
from shadowing_video_studio.speech_jobs import SpeechJobs


def speech_request(request_id="request-1", text="Reviewed sentence."):
    return GenerationRequest.model_validate(
        {
            "requestId": request_id,
            "operation": "speech",
            "payload": {"sentences": [{"id": "sentence-1", "text": text}]},
        }
    )


def video_request(request_id="request-1", text="Reviewed sentence."):
    return GenerationRequest.model_validate(
        {
            "requestId": request_id,
            "operation": "video",
            "payload": {
                "sentences": [
                    {
                        "id": "sentence-1",
                        "text": text,
                        "assetId": "a" * 32,
                    }
                ]
            },
        }
    )


class FakeVideo:
    def __init__(self):
        self.calls = []
        self.started = asyncio.Event()
        self.release = None
        self.error = None

    async def submit(
        self,
        sentences,
        *,
        background_asset_id=None,
        voice="Aiden",
        configuration_fingerprint=None,
    ):
        self.calls.append((sentences, background_asset_id, voice, configuration_fingerprint))
        self.started.set()
        if self.release:
            await self.release.wait()
        if self.error:
            raise self.error
        return {"id": "video-job-1", "status": "queued"}


def services(tmp_path, video=None):
    provider = FakeSpeech()
    speech = SpeechJobs(provider, SpeechAssets(tmp_path), HeavyJobGate())
    video = video or FakeVideo()
    return ApplicationControl(speech, video), speech, provider, video


def test_generation_request_cannot_self_approve_and_hides_review_capability(tmp_path):
    async def scenario():
        control, speech, _, _ = services(tmp_path)
        valid = {
            "requestId": "request-1",
            "operation": "speech",
            "payload": {"sentences": [{"id": "one", "text": "Private dialogue."}]},
        }
        with pytest.raises(ValidationError):
            GenerationRequest.model_validate({**valid, "approved": True})
        with pytest.raises(ValidationError):
            GenerationRequest.model_validate(
                {
                    **valid,
                    "payload": {**valid["payload"], "approved": True},
                }
            )

        result = await control.request_generation(GenerationRequest.model_validate(valid))
        assert result["state"] == "needs_review"
        assert "nonce" not in result and "payload" not in result
        listed = control.get_request("request-1")
        assert listed == result
        assert "Private dialogue." not in str(listed)
        await control.close()
        await speech.close()

    asyncio.run(scenario())


def test_request_idempotency_and_frozen_review_input(tmp_path):
    async def scenario():
        control, speech, _, _ = services(tmp_path)
        request = speech_request(text="Original wording.")
        first = await control.request_generation(request)
        repeated = await control.request_generation(speech_request(text="Original wording."))
        assert repeated == first
        assert first["requestId"] == "request-1"

        with pytest.raises(ControlError) as conflict:
            await control.request_generation(speech_request(text="Changed wording."))
        assert conflict.value.code == "idempotency_conflict"

        request.payload.sentences[0].text = "Mutated after submission."
        review = control.review("request-1")
        assert review.payload.sentences[0].text == "Original wording."
        assert review.payload.configurationFingerprint == "synthetic-config-v1"
        assert review.state == "needs_review"
        with pytest.raises(ControlError) as not_approved:
            await control.execute_request("request-1")
        assert not_approved.value.code == "review_required"
        assert control.get_request("request-1")["state"] == "needs_review"
        await control.close()
        await speech.close()

    asyncio.run(scenario())


def test_stale_configuration_fails_after_review_without_starting_generation(tmp_path):
    async def scenario():
        control, speech, provider, _ = services(tmp_path)
        await control.request_generation(speech_request())
        review = control.review("request-1")
        control.decide("request-1", review.nonce, "approve")
        provider.fingerprint = "synthetic-config-v2"

        result = await control.execute_request("request-1")
        assert result["state"] == "failed"
        assert result["error"]["code"] == "submission_failed"
        assert provider.calls == []
        assert await control.execute_request("request-1") == result
        await control.close()
        await speech.close()

    asyncio.run(scenario())


def test_concurrent_video_execution_submits_once_and_caches_result(tmp_path):
    async def scenario():
        video = FakeVideo()
        video.release = asyncio.Event()
        control, speech, _, _ = services(tmp_path, video)
        await control.request_generation(video_request())
        review = control.review("request-1")
        control.decide("request-1", review.nonce, "approve")

        first = asyncio.create_task(control.execute_request("request-1"))
        await video.started.wait()
        second_started = asyncio.Event()

        async def second_call():
            second_started.set()
            return await control.execute_request("request-1")

        second = asyncio.create_task(second_call())
        await second_started.wait()
        video.release.set()
        first_result, second_result = await asyncio.gather(first, second)
        assert first_result == second_result
        assert first_result["state"] == "submitted"
        assert first_result["result"] == {"id": "video-job-1", "status": "queued"}
        assert len(video.calls) == 1
        await control.close()
        await speech.close()

    asyncio.run(scenario())


def test_unknown_video_outcome_is_terminal_and_not_replayed(tmp_path):
    async def scenario():
        video = FakeVideo()
        video.error = RuntimeError("private renderer path")
        control, speech, _, _ = services(tmp_path, video)
        await control.request_generation(video_request())
        review = control.review("request-1")
        control.decide("request-1", review.nonce, "approve")

        result = await control.execute_request("request-1")
        assert result["state"] == "unknown_outcome"
        assert result["error"] == {
            "code": "unknown_outcome",
            "detail": "Inspect local jobs before retrying.",
        }
        assert "private renderer path" not in str(result)
        assert await control.execute_request("request-1") == result
        assert len(video.calls) == 1
        await control.close()
        await speech.close()

    asyncio.run(scenario())


def test_review_page_escapes_input_and_requires_matching_nonce(tmp_path):
    async def scenario():
        control, speech, _, _ = services(tmp_path)
        app = FastAPI()
        app.include_router(control_router)
        app.state.control = control
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000"
        ) as client:
            payload = GenerationRequest.model_validate(
                {
                    "requestId": "request-xss",
                    "operation": "speech",
                    "payload": {
                        "sentences": [
                            {
                                "id": '<img src=x onerror="alert(1)">',
                                "text": '<script>alert("dialogue")</script>',
                            }
                        ]
                    },
                }
            )
            await control.request_generation(payload)
            page = await client.get("/control/request-xss")
            assert page.status_code == 200
            assert '<img src=x onerror="alert(1)">' not in page.text
            assert '<script>alert("dialogue")</script>' not in page.text
            assert "&lt;script&gt;alert(&quot;dialogue&quot;)&lt;/script&gt;" in page.text

            rejected = await client.post(
                "/control/request-xss/decision",
                data={"nonce": "wrong", "decision": "approve"},
            )
            assert rejected.status_code == 403
            assert control.get_request("request-xss")["state"] == "needs_review"
            nonce = control.review("request-xss").nonce
            approved = await client.post(
                "/control/request-xss/decision",
                data={"nonce": nonce, "decision": "approve"},
            )
            assert approved.status_code == 303
            assert control.get_request("request-xss")["state"] == "approved"

            background_id = "a" * 32
            illustration_id = "b" * 32
            await control.request_generation(
                GenerationRequest.model_validate(
                    {
                        "requestId": "video-preview",
                        "operation": "video",
                        "payload": {
                            "backgroundAssetId": background_id,
                            "sentences": [
                                {
                                    "id": "video-sentence",
                                    "text": "Check both image previews.",
                                    "assetId": "c" * 32,
                                    "illustrationAssetId": illustration_id,
                                }
                            ],
                        },
                    }
                )
            )
            video_page = await client.get("/control/video-preview")
            assert video_page.status_code == 200
            assert f'<img src="/api/visuals/assets/{background_id}"' in video_page.text
            assert f'<img src="/api/visuals/assets/{illustration_id}"' in video_page.text
            assert "img-src 'self'" in video_page.headers["content-security-policy"]
        await control.close()
        await speech.close()

    asyncio.run(scenario())


def test_control_routes_reject_untrusted_host_and_origin(tmp_path):
    async def scenario():
        control, speech, _, _ = services(tmp_path)
        await control.request_generation(speech_request())
        review = control.review("request-1")
        app = FastAPI()
        app.include_router(control_router)
        app.state.control = control
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000"
        ) as client:
            for headers in (
                {"Host": "rebound.example"},
                {"Origin": "https://foreign.example"},
                {"Origin": "null"},
            ):
                response = await client.get("/control", headers=headers)
                assert response.status_code == 403
                response = await client.post(
                    "/control/request-1/decision",
                    headers=headers,
                    data={"nonce": review.nonce, "decision": "approve"},
                )
                assert response.status_code == 403
            assert control.get_request("request-1")["state"] == "needs_review"
        await control.close()
        await speech.close()

    asyncio.run(scenario())


def test_invalid_or_closed_review_nonce_never_approves(tmp_path):
    async def scenario():
        control, speech, _, _ = services(tmp_path)
        await control.request_generation(speech_request())
        review = control.review("request-1")
        original_nonce = review.nonce
        with pytest.raises(ControlError) as non_ascii:
            control.decide("request-1", "mïsmatched", "approve")
        assert non_ascii.value.status_code == 403
        assert control.get_request("request-1")["state"] == "needs_review"
        with pytest.raises(ControlError) as invalid:
            control.decide("request-1", "incorrect", "approve")
        assert invalid.value.status_code == 403
        assert control.get_request("request-1")["state"] == "needs_review"

        control.decide("request-1", original_nonce, "approve")
        with pytest.raises(ControlError) as closed:
            control.decide("request-1", original_nonce, "reject")
        assert closed.value.status_code == 403
        current_nonce = control.review("request-1").nonce
        with pytest.raises(ControlError) as closed:
            control.decide("request-1", current_nonce, "reject")
        assert closed.value.code == "review_closed"
        assert control.get_request("request-1")["state"] == "approved"
        await control.close()
        await speech.close()

    asyncio.run(scenario())


def test_rejection_and_expiry_both_block_execution(tmp_path):
    async def scenario():
        video = FakeVideo()
        control, speech, _, _ = services(tmp_path, video)
        await control.request_generation(video_request("rejected"))
        rejected_review = control.review("rejected")
        control.decide("rejected", rejected_review.nonce, "reject")
        with pytest.raises(ControlError) as rejected:
            await control.execute_request("rejected")
        assert rejected.value.code == "review_required"
        assert control.get_request("rejected")["state"] == "rejected"

        await control.request_generation(video_request("expired"))
        expired_review = control.review("expired")
        expired_review.expires = 0
        assert control.get_request("expired")["state"] == "expired"
        with pytest.raises(ControlError) as expired:
            await control.execute_request("expired")
        assert expired.value.code == "review_required"
        assert video.calls == []
        await control.close()
        await speech.close()

    asyncio.run(scenario())
