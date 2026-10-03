import asyncio
import json

import httpx
from test_speech_jobs import FakeSpeech

from shadowing_video_studio.main import app
from shadowing_video_studio.speech import HeavyJobGate
from shadowing_video_studio.speech_api import get_speech_service
from shadowing_video_studio.speech_assets import SpeechAssets
from shadowing_video_studio.speech_jobs import SpeechJobs


def test_speech_wire_and_assets_with_offline_provider(tmp_path):
    async def scenario():
        service = SpeechJobs(FakeSpeech(), SpeechAssets(tmp_path), HeavyJobGate())
        app.dependency_overrides[get_speech_service] = lambda: service
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000"
            ) as client:
                status = await client.get(
                    "/api/speech/status", headers={"Origin": "http://127.0.0.1:5173"}
                )
                assert status.json() == {
                    "available": True,
                    "reason": None,
                    "voice": "Aiden",
                    "model": "Qwen3-TTS-12Hz-0.6B-CustomVoice",
                    "backend": "cpu",
                }
                source = [{"id": "one", "text": " One. "}, {"id": "two", "text": "Two."}]
                submitted = await client.post("/api/speech/jobs", json={"sentences": source})
                assert submitted.status_code == 202
                await service.wait()
                result = (await client.get(f"/api/speech/jobs/{submitted.json()['id']}")).json()
                assert result["status"] == "completed" and result["error"] is None
                assert [
                    {"id": row["id"], "text": row["text"]} for row in result["sentences"]
                ] == source
                asset_id = result["sentences"][0]["assetId"]
                media = await client.get(f"/api/speech/assets/{asset_id}")
                assert media.status_code == 200 and media.headers["Content-Type"] == "audio/wav"
                assert media.content.startswith(b"RIFF")
                assert (await client.get("/api/speech/assets/not-an-id")).status_code == 404
                assert (await client.get("/api/speech/jobs/not-an-id")).status_code == 404
                for payload in [
                    {"sentences": source, "force": True},
                    {"sentences": [{"id": "one", "text": "private", "path": "/private"}]},
                    {"sentences": [{"id": "one", "text": "\ud800"}]},
                    {"sentences": source, "force": "true"},
                ]:
                    invalid = await client.post(
                        "/api/speech/jobs",
                        content=json.dumps(payload).encode(),
                        headers={"Content-Type": "application/json"},
                    )
                    assert invalid.status_code == 422
                    assert "private" not in invalid.text
        finally:
            app.dependency_overrides.clear()
            await service.close()

    asyncio.run(scenario())


def test_nonlocal_host_or_browser_origin_cannot_start_speech(tmp_path):
    async def scenario():
        provider = FakeSpeech()
        service = SpeechJobs(provider, SpeechAssets(tmp_path), HeavyJobGate())
        app.dependency_overrides[get_speech_service] = lambda: service
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000"
            ) as client:
                for headers in (
                    {"Host": "rebound.example"},
                    {"Origin": "https://foreign.example"},
                    {"Origin": "null"},
                ):
                    response = await client.post(
                        "/api/speech/jobs",
                        headers=headers,
                        json={"sentences": [{"id": "one", "text": "One."}]},
                    )
                    assert response.status_code == 403
                assert provider.calls == []
        finally:
            app.dependency_overrides.clear()
            await service.close()

    asyncio.run(scenario())
