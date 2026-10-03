import asyncio
import io
import wave

import pytest
from test_speech_jobs import FakeSpeech, write_wav

from shadowing_video_studio.speech import (
    MAX_SESSION_BYTES,
    MAX_WAV_BYTES,
    SpeechError,
    SpeechSentence,
)
from shadowing_video_studio.speech_assets import SpeechAssets


def asset_fixture(tmp_path):
    store = SpeechAssets(tmp_path)
    asset_id, path = store.allocate()
    write_wav(path)
    asset = store.register(asset_id, SpeechSentence("one", "One."), "config", path)
    return store, asset


def test_opaque_lookup_rejects_paths_unknown_ids_and_restart(tmp_path):
    store, asset = asset_fixture(tmp_path)
    for unknown in ("../private", "/absolute/file", "0" * 32, asset.id.upper()):
        with pytest.raises(SpeechError) as error:
            store.read(unknown)
        assert error.value.status_code == 404
    with pytest.raises(SpeechError):
        SpeechAssets(tmp_path).read(asset.id)
    assert asset.path.is_file()


def test_changed_missing_and_invalid_files_are_ineligible(tmp_path):
    store, asset = asset_fixture(tmp_path)
    asset.path.write_bytes(b"tampered")
    assert store.reusable(SpeechSentence("one", "One."), "config") is None
    with pytest.raises(SpeechError):
        store.read(asset.id)
    asset.path.unlink()
    with pytest.raises(SpeechError) as missing:
        store.read(asset.id)
    assert missing.value.status_code == 404


def test_invalid_wav_does_not_enter_cache(tmp_path):
    store = SpeechAssets(tmp_path)
    asset_id, path = store.allocate()
    path.write_bytes(b"not a waveform" * 8)
    with pytest.raises(SpeechError):
        store.register(asset_id, SpeechSentence("one", "One."), "config", path)
    assert store.reusable(SpeechSentence("one", "One."), "config") is None


@pytest.mark.parametrize(
    "channels,rate,width,frames",
    [(2, 24000, 2, 1), (1, 16000, 2, 1), (1, 24000, 1, 1), (1, 24000, 2, 0)],
)
def test_wav_format_contract(tmp_path, channels, rate, width, frames):
    store = SpeechAssets(tmp_path)
    asset_id, path = store.allocate()
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(channels)
        wav.setframerate(rate)
        wav.setsampwidth(width)
        wav.writeframes(b"\0" * channels * width * frames)
    path.write_bytes(buffer.getvalue())
    with pytest.raises(SpeechError):
        store.register(asset_id, SpeechSentence("one", "One."), "config", path)


def test_failed_allocations_cannot_bypass_storage_limit(tmp_path):
    store = SpeechAssets(tmp_path)
    for _ in range(MAX_SESSION_BYTES // MAX_WAV_BYTES):
        store.allocate()  # Even absent/partial outputs count against the reserved ceiling.
    with pytest.raises(SpeechError) as full:
        store.allocate()
    assert full.value.status_code == 409


def test_invalid_binding_and_register_identity_are_rejected(tmp_path):
    store, asset = asset_fixture(tmp_path)
    with pytest.raises(SpeechError):
        store.register(asset.id, SpeechSentence("one", "One."), "config", asset.path)
    with pytest.raises(SpeechError):
        store.register("a" * 32, SpeechSentence("one", "One."), "config", asset.path)


def test_parent_symlink_cannot_escape_workspace(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    link = workspace / "speech"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Windows account does not grant symlink creation")
    with pytest.raises(SpeechError):
        SpeechAssets(workspace).allocate()
    assert list(outside.iterdir()) == []


def test_provider_cannot_register_an_outside_path(tmp_path):
    store = SpeechAssets(tmp_path)
    asset_id, _ = store.allocate()
    outside = tmp_path / f"{asset_id}.wav"
    write_wav(outside)
    with pytest.raises(SpeechError):
        store.register(asset_id, SpeechSentence("one", "One."), "config", outside)


def test_no_wav_overwrite_in_provider_fixture(tmp_path):
    path = tmp_path / "existing.wav"
    write_wav(path)
    previous = path.read_bytes()
    with pytest.raises(FileExistsError):
        asyncio.run(FakeSpeech().generate("One.", path))
    assert path.read_bytes() == previous
