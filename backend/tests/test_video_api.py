import asyncio
import hashlib
import wave

import httpx
import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from shadowing_video_studio.main import invalid_request
from shadowing_video_studio.providers.process import ProcessResult
from shadowing_video_studio.speech import (
    VOICE,
    HeavyJobGate,
    SpeechCapabilities,
    SpeechError,
    SpeechReadiness,
    SpeechSentence,
    SpeechVoice,
)
from shadowing_video_studio.speech_assets import SpeechAssets
from shadowing_video_studio.speech_jobs import SpeechJobs
from shadowing_video_studio.video_api import get_video_service, router
from shadowing_video_studio.video_jobs import VideoJobs
from shadowing_video_studio.video_rendering import (
    RenderedVideo,
    VideoRenderingError,
    video_timeline,
)
from shadowing_video_studio.video_settings import (
    REQUIRED_BITSTREAM_FILTERS,
    REQUIRED_DECODERS,
    REQUIRED_DEMUXERS,
    REQUIRED_DRAWTEXT_OPTIONS,
    REQUIRED_ENCODERS,
    REQUIRED_FILTERS,
    REQUIRED_MUXERS,
    VideoSettings,
    VideoToolPreflight,
)
from shadowing_video_studio.visual_assets import VisualAsset, VisualAssetError


class FakeCapabilityRunner:
    def __init__(self):
        self.missing_drawtext = False
        self.missing_capability: str | None = None
        self.supports_text_shaping = True
        self.calls = []

    async def run(self, arguments, *, cwd, environment, timeout):
        self.calls.append(tuple(arguments))
        assert environment["HOME"] == str(cwd) and timeout == 10
        if arguments[-1] == "-version":
            return ProcessResult(0, b"ffprobe version synthetic\n")
        if arguments[-1] == "filter=drawtext":
            options = REQUIRED_DRAWTEXT_OPTIONS
            if self.supports_text_shaping:
                options = options | {"text_shaping"}
            return ProcessResult(
                0,
                "\n".join(
                    f" {option} <string> ..FV....... synthetic" for option in options
                ).encode(),
            )
        if arguments[-1] == "-bsfs":
            return ProcessResult(0, "\n".join(sorted(REQUIRED_BITSTREAM_FILTERS)).encode())
        options = {
            "-filters": ("...", REQUIRED_FILTERS),
            "-encoders": ("V.....", REQUIRED_ENCODERS),
            "-muxers": ("E", REQUIRED_MUXERS),
            "-decoders": ("V.....", REQUIRED_DECODERS),
            "-demuxers": ("D", REQUIRED_DEMUXERS),
        }
        flags, names = options[arguments[-1]]
        if arguments[-1] == "-filters" and self.missing_drawtext:
            names = names - {"drawtext"}
        if self.missing_capability in names:
            names = names - {self.missing_capability}
        return ProcessResult(0, "\n".join(f" {flags} {name} synthetic" for name in names).encode())


class FakeSpeech:
    fingerprint = "synthetic-approved-config"

    async def readiness(self):
        return SpeechReadiness(True)

    async def capabilities(self):
        voices = tuple(
            SpeechVoice(identifier, identifier, self.fingerprint_for_voice(identifier))
            for identifier in ("Aiden", "Ryan")
        )
        return SpeechCapabilities(True, voices=voices, default_voice=VOICE)

    def fingerprint_for_voice(self, voice):
        if voice == VOICE:
            return self.fingerprint
        return hashlib.sha256(f"{self.fingerprint}:{voice}".encode()).hexdigest()

    async def generate(self, _text, _destination, voice=VOICE):
        raise AssertionError("Video must not generate speech.")

    async def close(self):
        pass


class FakeRenderer:
    def __init__(self):
        self.calls = []
        self.backgrounds = []
        self.started = asyncio.Event()
        self.release = None
        self.fail = False

    async def render(self, sentences, directory, *, background=None, on_progress=None):
        self.calls.append(tuple(sentences))
        self.backgrounds.append(background)
        assert not list(directory.iterdir())
        self.started.set()
        if on_progress:
            on_progress(1, len(sentences))
        if self.release:
            await self.release.wait()
        if self.fail:
            (directory / "failed-evidence.txt").write_text("safe fixture")
            raise VideoRenderingError("Synthetic rendering failed.")
        for index in range(2, len(sentences) + 1):
            if on_progress:
                on_progress(index, len(sentences))
        output = directory / "video.mp4"
        with output.open("xb") as handle:
            handle.write(b"synthetic video fixture for opaque download")
        return RenderedVideo(
            output, sum(page.duration_seconds for page in video_timeline(sentences))
        )


def fixture_service(tmp_path):
    tool = tmp_path / "synthetic-tool"
    tool.write_text("fake executable")
    tool.chmod(0o755)
    font = tmp_path / "synthetic-font.ttf"
    font.write_bytes(b"font checked as a local file; fake renderer does not load it")
    settings = VideoSettings(tool, tool, font)
    assets = SpeechAssets(tmp_path)
    speech = SpeechJobs(FakeSpeech(), assets, HeavyJobGate())
    rows = []
    for identifier, text in (
        ("one", "One synthetic sentence."),
        ("two", "A second synthetic sentence."),
    ):
        asset_id, destination = assets.allocate()
        with destination.open("xb") as handle:
            with wave.open(handle, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(24000)
                wav.writeframes(b"\x01\x00" * 24000)
        assets.register(
            asset_id, SpeechSentence(identifier, text), speech.provider.fingerprint, destination
        )
        rows.append({"id": identifier, "text": text, "assetId": asset_id})
    renderer = FakeRenderer()
    return (
        VideoJobs(settings, speech, renderer, VideoToolPreflight(FakeCapabilityRunner())),
        renderer,
        rows,
    )


def test_missing_drawtext_blocks_readiness_and_submit_before_media_work(tmp_path):
    async def scenario():
        service, renderer, rows = fixture_service(tmp_path)
        runner = service._tool_preflight.runner
        runner.missing_drawtext = True
        try:
            async with client_for(service) as client:
                status = (await client.get("/api/video/status")).json()
                assert not status["available"] and "drawtext" in status["reason"]
                rejected = await client.post("/api/video/jobs", json={"sentences": rows})
                assert rejected.status_code == 503 and "drawtext" in rejected.json()["detail"]
                assert not renderer.calls and not service.gate.busy
                assert not (tmp_path / "video").exists()
                assert all(service.speech.assets.read(row["assetId"]) for row in rows)
                runner.missing_drawtext = False
                runner.supports_text_shaping = False
                assert (await client.get("/api/video/status")).json()["available"]
                assert not service._tool_preflight.supports_text_shaping
                calls = len(runner.calls)
                assert (await client.get("/api/video/status")).json()["available"]
                assert len(runner.calls) == calls
                with service.settings.ffmpeg_executable.open("ab") as handle:
                    handle.write(b"updated executable")
                runner.missing_drawtext = True
                assert not (await client.get("/api/video/status")).json()["available"]
                assert len(runner.calls) > calls
        finally:
            await service.close()
            await service.speech.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("capability", "reason"), [("png", "decoders"), ("image2pipe", "demuxers")]
)
def test_missing_png_input_support_blocks_video_submission(tmp_path, capability, reason):
    async def scenario():
        service, renderer, rows = fixture_service(tmp_path)
        runner = service._tool_preflight.runner
        runner.missing_capability = capability
        try:
            async with client_for(service) as client:
                status = (await client.get("/api/video/status")).json()
                assert not status["available"] and reason in status["reason"]
                rejected = await client.post("/api/video/jobs", json={"sentences": rows})
                assert rejected.status_code == 503 and reason in rejected.json()["detail"]
                assert not renderer.calls and not service.gate.busy
                assert not (tmp_path / "video").exists()
                assert all(service.speech.assets.read(row["assetId"]) for row in rows)
        finally:
            await service.close()
            await service.speech.close()

    asyncio.run(scenario())


def client_for(service):
    app = FastAPI()
    app.include_router(router)
    app.add_exception_handler(RequestValidationError, invalid_request)
    app.dependency_overrides[get_video_service] = lambda: service
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000"
    )


def test_video_wire_frozen_success_range_download_and_prior_exports(tmp_path):
    async def scenario():
        service, renderer, rows = fixture_service(tmp_path)
        try:
            async with client_for(service) as client:
                assert (await client.get("/api/video/status")).json() == {
                    "available": True,
                    "reason": None,
                }
                submitted = await client.post("/api/video/jobs", json={"sentences": rows})
                assert submitted.status_code == 202
                pending = submitted.json()
                assert pending == {
                    "id": pending["id"],
                    "status": "queued",
                    "completedSentences": 0,
                    "totalSentences": 2,
                    "assetId": None,
                    "durationSeconds": None,
                    "error": None,
                }
                await service.wait()
                completed = (await client.get(f"/api/video/jobs/{pending['id']}")).json()
                assert completed["status"] == "completed" and completed["completedSentences"] == 2
                assert completed["durationSeconds"] == 12 and completed["error"] is None
                asset_id = completed["assetId"]
                preview = await client.get(f"/api/video/assets/{asset_id}")
                assert preview.status_code == 200 and preview.headers["content-type"] == "video/mp4"
                assert preview.headers["content-disposition"].startswith("inline")
                assert preview.headers["cache-control"] == "no-store"
                ranged = await client.get(
                    f"/api/video/assets/{asset_id}", headers={"Range": "bytes=0-8"}
                )
                assert ranged.status_code == 206 and ranged.content == preview.content[:9]
                download = await client.get(f"/api/video/assets/{asset_id}?download=true")
                assert download.headers["content-disposition"].startswith("attachment")
                assert str(tmp_path) not in download.headers["content-disposition"]
                repeated = await client.post("/api/video/jobs", json={"sentences": rows})
                await service.wait()
                newer = service.get(repeated.json()["id"])
                assert newer["assetId"] != asset_id
                assert (
                    await client.get(f"/api/video/assets/{asset_id}")
                ).content == preview.content
                assert all(service.speech.assets.read(row["assetId"]) for row in rows)
                assert [item.id for item in renderer.calls[0]] == [row["id"] for row in rows]
                original = service.speech.assets.match(
                    rows[0]["assetId"],
                    SpeechSentence(rows[0]["id"], rows[0]["text"]),
                    service.speech.provider.fingerprint,
                )
                assert renderer.calls[0][0].audio_path != original.path
                assert renderer.calls[0][0].audio_path.read_bytes() == original.path.read_bytes()
        finally:
            await service.close()
            await service.speech.close()

    asyncio.run(scenario())


def test_missing_stale_or_changed_bindings_rejected_before_renderer(tmp_path):
    async def scenario():
        service, renderer, rows = fixture_service(tmp_path)
        try:
            async with client_for(service) as client:
                altered = [dict(rows[0], text="Edited sentence.")]
                assert (
                    await client.post("/api/video/jobs", json={"sentences": altered})
                ).status_code == 409
                missing = [dict(rows[0], assetId="0" * 32)]
                assert (
                    await client.post("/api/video/jobs", json={"sentences": missing})
                ).status_code == 404
                service.speech.provider.fingerprint = "changed-config"
                assert (
                    await client.post("/api/video/jobs", json={"sentences": rows})
                ).status_code == 409
                service.speech.provider.fingerprint = "synthetic-approved-config"
                source = service.speech.assets.match(
                    rows[0]["assetId"],
                    SpeechSentence(rows[0]["id"], rows[0]["text"]),
                    service.speech.provider.fingerprint,
                )
                with source.path.open("r+b") as handle:
                    handle.seek(-1, 2)
                    handle.write(b"\x7f")
                assert (
                    await client.post("/api/video/jobs", json={"sentences": rows})
                ).status_code == 404
                assert not renderer.calls and not service.gate.busy
                assert not (tmp_path / "video").exists()
        finally:
            await service.close()
            await service.speech.close()

    asyncio.run(scenario())


def test_video_rejects_audio_that_does_not_match_selected_voice(tmp_path):
    async def scenario():
        service, renderer, rows = fixture_service(tmp_path)
        try:
            async with client_for(service) as client:
                response = await client.post(
                    "/api/video/jobs",
                    json={
                        "sentences": rows,
                        "voice": "Ryan",
                        "configurationFingerprint": service.speech.provider.fingerprint_for_voice(
                            "Ryan"
                        ),
                    },
                )
                assert response.status_code == 409
                assert "audio" in response.json()["detail"].lower()
                assert not renderer.calls and not service.gate.busy
                assert not (tmp_path / "video").exists()
        finally:
            await service.close()
            await service.speech.close()

    asyncio.run(scenario())


def test_shared_busy_gate_failure_preservation_and_explicit_retry(tmp_path):
    async def scenario():
        service, renderer, rows = fixture_service(tmp_path)
        renderer.release = asyncio.Event()
        renderer.fail = True
        try:
            async with client_for(service) as client:
                started = await client.post("/api/video/jobs", json={"sentences": rows})
                await renderer.started.wait()
                active = service.get(started.json()["id"])
                assert active["status"] == "running" and active["completedSentences"] == 1
                assert (
                    active["assetId"] is None
                    and active["durationSeconds"] is None
                    and active["error"] is None
                )
                assert (
                    await client.post("/api/video/jobs", json={"sentences": rows})
                ).status_code == 409
                with pytest.raises(SpeechError) as busy:
                    await service.speech.submit([SpeechSentence("new", "New.")])
                assert busy.value.status_code == 409
                renderer.release.set()
                await service.wait()
                failed = service.get(started.json()["id"])
                assert failed["status"] == "failed" and failed["error"]
                assert failed["assetId"] is None and failed["durationSeconds"] is None
                assert not service.gate.busy and all(
                    service.speech.assets.read(row["assetId"]) for row in rows
                )
                evidence = tmp_path / "video" / failed["id"] / "render" / "failed-evidence.txt"
                assert evidence.exists()
                for _ in range(3):
                    another = await client.post("/api/video/jobs", json={"sentences": rows})
                    assert another.status_code == 202
                    await service.wait()
                    assert service.get(another.json()["id"])["status"] == "failed"
                assert service._reserved_bytes == sum(
                    path.stat().st_size
                    for path in (tmp_path / "video").rglob("*")
                    if path.is_file()
                )
                renderer.fail = False
                retry = await client.post("/api/video/jobs", json={"sentences": rows})
                await service.wait()
                assert service.get(retry.json()["id"])["status"] == "completed"
                assert evidence.exists() and len(renderer.calls) == 5
        finally:
            await service.close()
            await service.speech.close()

    asyncio.run(scenario())


def test_request_path_protection_and_changed_export_are_safe(tmp_path):
    async def scenario():
        service, renderer, rows = fixture_service(tmp_path)
        try:
            async with client_for(service) as client:
                for headers in (
                    {"Host": "foreign.example"},
                    {"Origin": "https://foreign.example"},
                    {"Origin": "null"},
                ):
                    assert (
                        await client.post(
                            "/api/video/jobs", headers=headers, json={"sentences": rows}
                        )
                    ).status_code == 403
                arbitrary = {
                    "sentences": [dict(rows[0], audio_path="/private/path")],
                    "output": "/private/output",
                }
                blocked = await client.post("/api/video/jobs", json=arbitrary)
                assert blocked.status_code == 422 and "private" not in blocked.text
                assert (await client.get("/api/video/assets/not-a-file-id")).status_code == 404
                assert not renderer.calls
                queued = await client.post("/api/video/jobs", json={"sentences": rows})
                await service.wait()
                asset_id = service.get(queued.json()["id"])["assetId"]
                output = service.asset(asset_id).path
                with output.open("ab") as handle:
                    handle.write(b"changed")
                altered = await client.get(f"/api/video/assets/{asset_id}")
                assert altered.status_code == 404 and str(tmp_path) not in altered.text
        finally:
            await service.close()
            await service.speech.close()

    asyncio.run(scenario())


def test_image_selection_freezes_bytes_and_missing_changed_kind_blocks_tools(tmp_path):
    class FrozenLibrary:
        def __init__(self):
            self.assets = {}

        def get(self, asset_id, kind=None):
            asset = self.assets.get(asset_id)
            if not asset or asset.kind != kind or not asset.path.is_file():
                raise VisualAssetError("Select or upload an available image.", 404)
            return asset

        def read(self, asset_id, kind=None):
            return self.get(asset_id, kind).path.read_bytes()

    async def scenario():
        service, renderer, rows = fixture_service(tmp_path)
        service.visuals = library = FrozenLibrary()
        for character, kind in (("a", "background"), ("b", "illustration")):
            path = tmp_path / f"source-{kind}.png"
            content = f"synthetic validated {kind}".encode()
            path.write_bytes(content)
            library.assets[character * 32] = VisualAsset(
                character * 32,
                kind,
                f"{kind}.png",
                "image/png",
                1,
                1,
                len(content),
                hashlib.sha256(content).hexdigest(),
                path,
            )
        background = library.assets["a" * 32]
        illustration = library.assets["b" * 32]
        original_background = background.path.read_bytes()
        original_illustration = illustration.path.read_bytes()
        try:
            async with client_for(service) as client:
                for bad_background in ("0" * 32, illustration.id):
                    rejected = await client.post(
                        "/api/video/jobs",
                        json={"sentences": rows, "backgroundAssetId": bad_background},
                    )
                    assert rejected.status_code == 404
                illustration.path.write_bytes(b"changed")
                selected = [dict(rows[1], illustrationAssetId=illustration.id), rows[0]]
                changed = await client.post(
                    "/api/video/jobs",
                    json={"sentences": selected, "backgroundAssetId": background.id},
                )
                assert changed.status_code == 409
                assert not renderer.calls and not service._tool_preflight.runner.calls
                assert not service.gate.busy and not (tmp_path / "video").exists()
                illustration.path.write_bytes(original_illustration)
                submitted = await client.post(
                    "/api/video/jobs",
                    json={"sentences": selected, "backgroundAssetId": background.id},
                )
                assert submitted.status_code == 202
                # Source mutation after acceptance cannot alter the frozen bytes for this attempt.
                background.path.write_bytes(b"later source change")
                illustration.path.write_bytes(b"later source change")
                await service.wait()
                assert service.get(submitted.json()["id"])["status"] == "completed"
                frozen = renderer.calls[0]
                assert [item.id for item in frozen] == [rows[1]["id"], rows[0]["id"]]
                assert frozen[0].illustration.id == illustration.id
                assert frozen[0].illustration.path.read_bytes() == original_illustration
                assert frozen[1].illustration is None
                assert renderer.backgrounds[0].path.read_bytes() == original_background
                assert all(service.speech.assets.read(row["assetId"]) for row in rows)
        finally:
            await service.close()
            await service.speech.close()

    asyncio.run(scenario())
