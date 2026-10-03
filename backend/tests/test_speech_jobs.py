import asyncio
import wave

import pytest

from shadowing_video_studio.speech import HeavyJobGate, SpeechError, SpeechReadiness, SpeechSentence
from shadowing_video_studio.speech_assets import SpeechAssets
from shadowing_video_studio.speech_jobs import SpeechJobs, validate_sentences


def write_wav(path, frames=240):
    with path.open("xb") as handle:
        with wave.open(handle, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(24000)
            wav.writeframes(b"\x01\x00" * frames)


class FakeSpeech:
    fingerprint = "synthetic-config-v1"

    def __init__(self):
        self.calls = []
        self.fail = set()
        self.available = True
        self.started = asyncio.Event()
        self.release = None
        self.closed = False

    async def readiness(self):
        return SpeechReadiness(self.available, None if self.available else "Configure the runtime.")

    async def generate(self, text, destination):
        self.calls.append((text, destination))
        self.started.set()
        if self.release:
            await self.release.wait()
        if text in self.fail:
            raise RuntimeError("private local path and source diagnostic")
        write_wav(destination)

    async def close(self):
        self.closed = True


def test_frozen_progress_reuse_regenerate_and_binding(tmp_path):
    async def scenario():
        provider = FakeSpeech()
        assets = SpeechAssets(tmp_path)
        service = SpeechJobs(provider, assets, HeavyJobGate())
        source = [SpeechSentence("first", " First sentence. "), SpeechSentence("second", "Second.")]
        pending = await service.submit(source)
        assert pending["status"] == "queued"
        assert all(row["status"] == "pending" for row in pending["sentences"])
        pending["sentences"][0]["text"] = "mutated response"
        await service.wait()
        finished = service.get(pending["id"])
        assert finished["status"] == "completed"
        assert finished["sentences"][0]["text"] == source[0].text
        first_asset = finished["sentences"][0]["assetId"]
        assert len(assets.read(first_asset)) > 44
        assert assets.match(first_asset, source[0], provider.fingerprint).duration_seconds == 0.01
        reused = await service.submit(source)
        assert reused["status"] == "completed"
        assert all(row["reused"] for row in reused["sentences"])
        assert len(provider.calls) == 2
        regenerated = await service.submit(source[:1], force=True)
        await service.wait()
        new_row = service.get(regenerated["id"])["sentences"][0]
        assert new_row["assetId"] != first_asset and not new_row["reused"]
        assert assets.read(first_asset)  # Prior selected WAV is never overwritten.
        for altered, fingerprint in [
            (SpeechSentence("first", "Edited."), provider.fingerprint),
            (SpeechSentence("replacement", source[0].text), provider.fingerprint),
            (source[0], "changed-config"),
        ]:
            with pytest.raises(SpeechError) as error:
                assets.match(first_asset, altered, fingerprint)
            assert error.value.status_code == 409
        await service.close()
        assert provider.closed

    asyncio.run(scenario())


def test_partial_failure_keeps_success_and_retries_only_uncached_rows(tmp_path):
    async def scenario():
        provider = FakeSpeech()
        provider.fail.add("Fail.")
        service = SpeechJobs(provider, SpeechAssets(tmp_path), HeavyJobGate())
        source = [SpeechSentence("ok", "Success."), SpeechSentence("bad", "Fail.")]
        job = await service.submit(source)
        await service.wait()
        failed = service.get(job["id"])
        assert failed["status"] == "failed" and failed["error"]
        assert [row["status"] for row in failed["sentences"]] == ["ready", "failed"]
        assert "private" not in str(failed)
        assert failed["sentences"][1]["assetId"] is None
        provider.fail.clear()
        retried = await service.submit(source)
        await service.wait()
        result = service.get(retried["id"])
        assert result["status"] == "completed"
        assert result["sentences"][0]["reused"]
        assert [text for text, _ in provider.calls] == ["Success.", "Fail.", "Fail."]
        await service.close()

    asyncio.run(scenario())


def test_gate_rejects_second_heavy_job_but_allows_cached_response(tmp_path):
    async def scenario():
        provider = FakeSpeech()
        gate = HeavyJobGate()
        service = SpeechJobs(provider, SpeechAssets(tmp_path), gate)
        old = [SpeechSentence("cached", "Cached.")]
        await service.submit(old)
        await service.wait()
        provider.started.clear()
        provider.release = asyncio.Event()
        active = await service.submit([SpeechSentence("new", "New.")])
        await provider.started.wait()
        assert gate.busy
        assert service.get(active["id"])["sentences"][0]["status"] == "generating"
        with pytest.raises(SpeechError) as conflict:
            await service.submit([SpeechSentence("other", "Other.")])
        assert conflict.value.status_code == 409
        assert (await service.submit(old))["status"] == "completed"
        provider.release.set()
        await service.wait()
        assert not gate.busy
        # A later renderer can own the exact same gate without a second scheduler.
        assert gate.claim("video-job")
        with pytest.raises(SpeechError):
            await service.submit([SpeechSentence("third", "Third.")])
        gate.release("wrong-owner")
        assert gate.busy
        gate.release("video-job")
        await service.close()

    asyncio.run(scenario())


def test_shutdown_finishes_all_nonterminal_rows_safely(tmp_path):
    async def scenario():
        provider = FakeSpeech()
        provider.release = asyncio.Event()
        gate = HeavyJobGate()
        service = SpeechJobs(provider, SpeechAssets(tmp_path), gate)
        job = await service.submit([SpeechSentence("one", "One."), SpeechSentence("two", "Two.")])
        await provider.started.wait()
        await service.close()
        result = service.get(job["id"])
        assert result["status"] == "failed" and result["error"]
        assert all(row["status"] == "failed" and row["error"] for row in result["sentences"])
        assert provider.closed and not gate.busy
        with pytest.raises(SpeechError) as stopped:
            await service.submit([SpeechSentence("one", "One.")])
        assert stopped.value.status_code == 503

    asyncio.run(scenario())


def test_unavailable_preflight_releases_gate_without_generation(tmp_path):
    async def scenario():
        provider = FakeSpeech()
        provider.available = False
        gate = HeavyJobGate()
        service = SpeechJobs(provider, SpeechAssets(tmp_path), gate)
        with pytest.raises(SpeechError) as error:
            await service.submit([SpeechSentence("one", "One.")])
        assert error.value.status_code == 503
        assert not gate.busy and not provider.calls

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "sentences,force",
    [
        ([], False),
        ([SpeechSentence("one", "")], False),
        ([SpeechSentence("one", " ")], False),
        ([SpeechSentence(" ", "Text")], False),
        ([SpeechSentence("same", "One"), SpeechSentence("same", "Two")], False),
        ([SpeechSentence("one", "😀" * 2001)], False),
        ([SpeechSentence("one", "\ud800")], False),
        ([SpeechSentence("\ud800", "One")], False),
        ([SpeechSentence(str(index), "One") for index in range(101)], False),
        ([SpeechSentence(str(index), "x" * 4000) for index in range(6)], False),
        ([SpeechSentence("one", "One"), SpeechSentence("two", "Two")], True),
    ],
    ids=[
        "empty",
        "empty-text",
        "blank",
        "blank-id",
        "duplicate",
        "utf16",
        "text-surrogate",
        "id-surrogate",
        "count",
        "total",
        "multi-force",
    ],
)
def test_invalid_frozen_requests(sentences, force):
    with pytest.raises(SpeechError) as error:
        validate_sentences(sentences, force)
    assert error.value.status_code == 422
