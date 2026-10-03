import asyncio
import json
import struct
import zlib
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from shadowing_video_studio.providers.image_probe import ImageProbe
from shadowing_video_studio.providers.process import ProcessResult
from shadowing_video_studio.speech import HeavyJobGate
from shadowing_video_studio.visual_api import VisualService, router
from shadowing_video_studio.visual_assets import (
    MAX_IMAGE_BYTES,
    VisualAssetError,
    VisualLibrary,
    image_metadata,
)


def png(width=2, height=1):
    def chunk(tag, content):
        return (
            struct.pack(">I", len(content))
            + tag
            + content
            + struct.pack(">I", zlib.crc32(tag + content))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\0\xff\0\0\0\xff\0"))
        + chunk(b"IEND", b"")
    )


class FakeProbe:
    calls = 0
    fail = False

    async def validate(self, path, mime_type):
        self.calls += 1
        assert path.name == "image.png" and mime_type == "image/png"
        if self.fail:
            raise VisualAssetError("The image could not be decoded.")
        _, width, height = image_metadata(path.read_bytes())
        return width, height


def imported(tmp_path, kind="background"):
    probe = FakeProbe()
    library = VisualLibrary(tmp_path, probe)
    asset = asyncio.run(library.import_asset(kind, "test.png", png()))
    return library, asset, probe


def test_local_upload_api_preview_restart_and_safe_failures(tmp_path):
    async def scenario():
        app = FastAPI()
        app.include_router(router)
        app.state.visuals = VisualService(VisualLibrary(tmp_path, FakeProbe()))
        gate = HeavyJobGate()
        app.state.speech = SimpleNamespace(gate=gate)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
        ) as client:
            url = "/api/visuals/assets?kind=background&name=sample.png"
            denied = await client.post(url, content=png(), headers={"Origin": "https://evil.test"})
            assert denied.status_code == 403
            assert gate.claim("running-media")
            assert (await client.post(url, content=png())).status_code == 409
            gate.release("running-media")
            uploaded = await client.post(url, content=png())
            assert uploaded.status_code == 201
            asset = uploaded.json()
            assert asset["available"] and asset["mimeType"] == "image/png"
            assert "path" not in asset
            preview = await client.get(f"/api/visuals/assets/{asset['id']}")
            assert preview.content == png()
            assert preview.headers["x-content-type-options"] == "nosniff"
            app.state.visuals = VisualService(VisualLibrary(tmp_path, FakeProbe()))
            assert (await client.get("/api/visuals/assets")).json() == {"assets": [asset]}
            assert (await client.post(url, content=b"not an image")).status_code == 400
            assert (
                await client.post(
                    url, content=b"", headers={"Content-Length": str(MAX_IMAGE_BYTES + 1)}
                )
            ).status_code == 413
            assert (await client.get("/api/visuals/assets")).json() == {"assets": [asset]}
            assert gate.claim("after-upload-error")
            gate.release("after-upload-error")

    asyncio.run(scenario())


def test_upload_list_restart_and_no_overwrite(tmp_path):
    library, first, probe = imported(tmp_path)
    second = asyncio.run(library.import_asset("background", "test.png", png()))
    third = asyncio.run(library.import_asset("illustration", "portrait.png", png()))
    assert len({first.id, second.id, third.id}) == 3
    assert first.path.read_bytes() == second.path.read_bytes() == png()
    restarted = VisualLibrary(tmp_path, FakeProbe())
    assert {item["id"] for item in restarted.list_assets()} == {first.id, second.id, third.id}
    assert restarted.get(first.id, "background") == first
    assert restarted.read(third.id, "illustration") == png()
    assert probe.calls == 3
    assert restarted.probe.calls == 0
    with pytest.raises(VisualAssetError):
        restarted.get(first.id, "illustration")


def test_invalid_oversized_and_corrupt_uploads_leave_prior_assets(tmp_path):
    library, asset, probe = imported(tmp_path)
    for content in (b"not an image", b"x" * (MAX_IMAGE_BYTES + 1), png(8193, 1), png(8192, 8192)):
        with pytest.raises(VisualAssetError):
            asyncio.run(library.import_asset("background", "bad.png", content))
    assert probe.calls == 1  # Limits are enforced before an external decoder starts.
    probe.fail = True
    with pytest.raises(VisualAssetError):
        asyncio.run(library.import_asset("background", "corrupt.png", png()))
    assert library.list_assets() == [asset.dto()]
    assert library.read(asset.id) == png()


def test_missing_changed_files_list_as_unavailable_and_reject_reads(tmp_path):
    library, asset, _ = imported(tmp_path)
    original = asset.path.read_bytes()
    asset.path.write_bytes(original[:-1] + b"x")
    assert library.list_assets()[0]["available"] is False
    with pytest.raises(VisualAssetError):
        library.get(asset.id)
    asset.path.unlink()
    assert library.list_assets()[0]["available"] is False
    with pytest.raises(VisualAssetError):
        library.read(asset.id)


def test_path_and_metadata_do_not_select_arbitrary_files(tmp_path):
    library, asset, _ = imported(tmp_path)
    for asset_id in ("../private", "/absolute/file", asset.id.upper(), "0" * 32):
        with pytest.raises(VisualAssetError):
            library.get(asset_id)
    metadata_path = asset.path.parent / "asset.json"
    metadata = json.loads(metadata_path.read_bytes())
    metadata["path"] = str(tmp_path / "private.png")
    metadata_path.write_text(json.dumps(metadata))
    assert library.list_assets() == []
    with pytest.raises(VisualAssetError):
        library.read(asset.id)
    assert asset.path.read_bytes() == png()
    with pytest.raises(VisualAssetError):
        VisualLibrary(Path("relative-workspace"), FakeProbe())


def test_linked_library_directory_never_writes_outside(tmp_path):
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    try:
        (workspace / "visuals").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Windows account does not grant symlink creation")
    library = VisualLibrary(workspace, FakeProbe())
    with pytest.raises(VisualAssetError):
        asyncio.run(library.import_asset("background", "test.png", png()))
    assert list(outside.iterdir()) == []


def test_image_decode_uses_fixed_local_protocol_and_reports_safe_failure(tmp_path):
    class Runner:
        def __init__(self):
            self.calls = []
            self.fail = False

        async def run(self, arguments, **options):
            self.calls.append((arguments, options))
            if self.fail:
                return ProcessResult(1, b"", b"private local path /secret")
            if "-show_entries" in arguments:
                return ProcessResult(
                    0,
                    json.dumps(
                        {
                            "streams": [
                                {
                                    "codec_name": "png",
                                    "codec_type": "video",
                                    "width": 2,
                                    "height": 1,
                                }
                            ]
                        }
                    ).encode(),
                )
            return ProcessResult(0, b"")

    runner = Runner()
    probe = ImageProbe(tmp_path / "ffmpeg", tmp_path / "ffprobe", runner)
    path = tmp_path / "image.png"
    path.write_bytes(png())
    assert asyncio.run(probe.validate(path, "image/png")) == (2, 1)
    for arguments, options in runner.calls:
        assert arguments[arguments.index("-protocol_whitelist") + 1] == "file"
        assert arguments[arguments.index("-i") + 1] == "image.png"
        assert options["cwd"] == tmp_path and options["timeout"] == 20
    assert "-xerror" in runner.calls[1][0] and "explode" in runner.calls[1][0]
    runner.fail = True
    with pytest.raises(VisualAssetError) as error:
        asyncio.run(probe.validate(path, "image/png"))
    assert "private" not in error.value.detail and "/secret" not in error.value.detail


def test_storage_budget_cannot_be_bypassed_by_failed_import(tmp_path, monkeypatch):
    library, asset, probe = imported(tmp_path)
    monkeypatch.setattr("shadowing_video_studio.visual_assets.MAX_VISUAL_RECORDS", 2)
    probe.fail = True
    with pytest.raises(VisualAssetError):
        asyncio.run(library.import_asset("background", "corrupt.png", png()))
    probe.fail = False
    with pytest.raises(VisualAssetError) as error:
        asyncio.run(library.import_asset("background", "another.png", png()))
    assert error.value.status_code == 409
    assert library.list_assets() == [asset.dto()]
