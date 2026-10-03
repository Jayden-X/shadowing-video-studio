import asyncio
import io
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from shadowing_video_studio.providers import qwen, qwen_worker
from shadowing_video_studio.providers.process import ProcessResult
from shadowing_video_studio.providers.qwen import QwenSpeechProvider, runtime_environment
from shadowing_video_studio.speech import SpeechError
from shadowing_video_studio.speech_assets import SpeechAssets
from shadowing_video_studio.speech_settings import MODEL_REVISION, SpeechSettings


def settings_fixture(tmp_path, speakers=None):
    speakers = {"aiden": 0, "ryan": 1} if speakers is None else speakers
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    model = tmp_path / "cache" / MODEL_REVISION
    model.mkdir(parents=True)
    (model / "config.json").write_text(
        json.dumps(
            {
                "model_type": "qwen3_tts",
                "tts_model_type": "custom_voice",
                "tts_model_size": "0b6",
                "talker_config": {"spk_id": speakers},
            }
        )
    )
    (model / "model.safetensors").touch()
    (model / "speech_tokenizer").mkdir()
    (model / "speech_tokenizer" / "model.safetensors").touch()
    return SpeechSettings(workspace=workspace, model_path=model, python_executable=sys.executable)


def test_readiness_does_not_load_model_or_write_runtime(tmp_path, monkeypatch):
    settings = settings_fixture(tmp_path)
    calls = []

    async def probe(_runner, arguments, **options):
        calls.append((arguments, options))
        return ProcessResult(0, b'{"available":true}')

    monkeypatch.setattr(qwen.SubprocessRunner, "run", probe)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "private")
    provider = QwenSpeechProvider(settings, SpeechAssets(settings.workspace))
    assert asyncio.run(provider.readiness()).available
    assert calls[0][0][-1] == "probe" and "-I" in calls[0][0] and "-B" in calls[0][0]
    assert "DEEPSEEK_API_KEY" not in calls[0][1]["environment"]
    assert list(settings.workspace.iterdir()) == []
    bad = SpeechSettings(
        workspace=settings.workspace, model_path=settings.model_path.with_name("0" * 40)
    )
    assert not asyncio.run(QwenSpeechProvider(bad).readiness()).available
    assert len(calls) == 1


def test_capabilities_read_only_frozen_speaker_config_without_loading_model(tmp_path, monkeypatch):
    async def probe(_runner, _arguments, **_options):
        return ProcessResult(0, b'{"available":true}')

    monkeypatch.setattr(qwen.SubprocessRunner, "run", probe)
    settings = settings_fixture(tmp_path)
    provider = QwenSpeechProvider(settings, SpeechAssets(settings.workspace))
    capabilities = asyncio.run(provider.capabilities())
    assert capabilities.available and capabilities.reason is None
    assert capabilities.default_voice == "Aiden"
    assert [(voice.id, voice.label) for voice in capabilities.voices] == [
        ("Aiden", "Aiden"),
        ("Ryan", "Ryan"),
    ]
    assert all(len(voice.configuration_fingerprint) == 64 for voice in capabilities.voices)
    assert provider._process is None
    assert list(settings.workspace.iterdir()) == []

    config_path = settings.model_path / "config.json"
    config = json.loads(config_path.read_bytes())
    config["talker_config"]["spk_id"] = {"Invalid Voice": 0}
    config_path.write_text(json.dumps(config))
    unavailable = asyncio.run(provider.capabilities())
    assert not unavailable.available and unavailable.reason
    assert unavailable.voices == () and unavailable.default_voice is None
    assert provider._process is None
    assert list(settings.workspace.iterdir()) == []


def test_verified_generation_requires_eos_and_restores_vendor_method():
    for sequence, raises, expected in [
        ([[1, 99]], False, None),
        ([[1, 2]], False, qwen_worker.IncompleteSpeech),
        (None, False, qwen_worker.IncompleteSpeech),
        ([[1, 99]], True, RuntimeError),
    ]:

        def original_generate(*_arguments, _raises=raises, _sequence=sequence, **_keywords):
            if _raises:
                raise RuntimeError("synthetic")
            return SimpleNamespace(sequences=SimpleNamespace(tolist=lambda: _sequence))

        talker = SimpleNamespace(generate=original_generate)
        model = SimpleNamespace(
            model=SimpleNamespace(
                talker=talker,
                config=SimpleNamespace(talker_config=SimpleNamespace(codec_eos_token_id=99)),
            )
        )
        seen = []

        def custom_voice(_seen=seen, _talker=talker, **parameters):
            _seen.append(parameters)
            _talker.generate()
            return (["synthetic samples"], 24000)

        model.generate_custom_voice = custom_voice
        if expected:
            with pytest.raises(expected):
                qwen_worker.generate_verified(model, "Sentence.")
        else:
            assert qwen_worker.generate_verified(model, "Sentence.")[1] == 24000
        assert talker.generate is original_generate
        assert seen[0]["max_new_tokens"] == 4096
        assert seen[0]["speaker"] == "Aiden" and seen[0]["language"] == "English"


class WorkerInput:
    def __init__(self, process):
        self.process = process
        self.closed = False
        self.requests = []

    def write(self, payload):
        self.requests.append(json.loads(payload))
        self.process.started.set()
        if self.process.response is not None:
            self.process.stdout.feed_data(self.process.response)

    async def drain(self):
        pass

    def close(self):
        self.closed = True


class FakeWorker:
    def __init__(self, response=b'{"ok":true}\n'):
        self.pid = 987654321
        self.returncode = None
        self.stdout = asyncio.StreamReader()
        self.stdin = WorkerInput(self)
        self.response = response
        self.started = asyncio.Event()
        self.ended = asyncio.Event()
        self.waited = False

    def kill(self):
        if self.returncode is None:
            self.returncode = -1
            self.stdout.feed_eof()
            self.ended.set()

    async def wait(self):
        self.waited = True
        await self.ended.wait()
        return self.returncode


def install_worker(monkeypatch, worker):
    calls = []

    async def spawn(*arguments, **options):
        calls.append((arguments, options))
        return worker

    class FakeJob:
        def attach_and_resume(self, _pid):
            pass

        def close(self):
            worker.kill()

    monkeypatch.setattr(qwen.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(qwen, "WindowsJob", FakeJob)
    monkeypatch.setattr(qwen.os, "killpg", lambda *_: worker.kill(), raising=False)
    return calls


def test_persistent_worker_uses_stdin_and_scoped_environment(tmp_path, monkeypatch):
    async def scenario():
        settings = settings_fixture(tmp_path)
        assets = SpeechAssets(settings.workspace)
        worker = FakeWorker()
        calls = install_worker(monkeypatch, worker)
        provider = QwenSpeechProvider(settings, assets)
        for source, voice in (("First.", "Aiden"), ("Second.", "Ryan")):
            _, path = assets.allocate()
            await provider.generate(source, path, voice)
        assert len(calls) == 1  # One process/model across sentences.
        assert [item["text"] for item in worker.stdin.requests] == ["First.", "Second."]
        assert [item["voice"] for item in worker.stdin.requests] == ["Aiden", "Ryan"]
        arguments, options = calls[0]
        assert "First." not in arguments and "shell" not in options
        assert arguments[1:3] == ("-I", "-B")
        assert options["cwd"].is_relative_to(settings.workspace)
        environment = options["env"]
        for key in ("HOME", "TMPDIR", "TMP", "TEMP", "HF_HOME", "TORCH_HOME", "XDG_CACHE_HOME"):
            assert Path(environment[key]).is_relative_to(settings.workspace)
        assert environment["HF_HUB_OFFLINE"] == "1"
        await provider.close()
        assert worker.returncode is not None and worker.waited and worker.stdin.closed

    asyncio.run(scenario())


def test_worker_forwards_supported_speaker_and_skips_unsupported_synthesis(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    runtime = workspace / "speech" / "session" / "runtime"
    runtime.mkdir(parents=True)
    model_path = tmp_path / "model"
    model_path.mkdir()
    supported_destination = runtime.parent / "supported.wav"
    unsupported_destination = runtime.parent / "unsupported.wav"
    assert supported_destination.parent.resolve() == runtime.parent
    requests = [
        {
            "text": "Unsupported voice.",
            "destination": str(unsupported_destination),
            "voice": "Ghost",
        },
        {"text": "Supported voice.", "destination": str(supported_destination), "voice": "Ryan"},
    ]

    class FakeInput:
        def __init__(self):
            self.buffer = io.BytesIO(
                b"".join(json.dumps(request).encode() + b"\n" for request in requests)
            )

    class FakeOutput:
        def fileno(self):
            return 9321

    class FakeProtocol:
        def __init__(self):
            self.lines = []

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def write(self, line):
            self.lines.append(line)

        def flush(self):
            pass

    class FakeModel:
        def get_supported_speakers(self):
            return ["aiden", "ryan"]

    model = FakeModel()
    loads = []
    torch_calls = []
    qwen_package = ModuleType("qwen_tts")

    class FakeQwenModel:
        @classmethod
        def from_pretrained(cls, *_args, **_kwargs):
            loads.append(True)
            return model

    qwen_package.Qwen3TTSModel = FakeQwenModel
    torch_package = ModuleType("torch")
    torch_package.set_num_threads = lambda count: torch_calls.append(count)
    torch_package.float32 = object()
    monkeypatch.setitem(sys.modules, "qwen_tts", qwen_package)
    monkeypatch.setitem(sys.modules, "torch", torch_package)

    protocol = FakeProtocol()
    writes = []

    def write_verified(_model, text, destination, voice):
        writes.append((text, destination, voice))

    monkeypatch.setattr(qwen_worker, "write_verified_audio", write_verified)
    monkeypatch.setattr(qwen_worker.sys, "stdin", FakeInput())
    monkeypatch.setattr(qwen_worker.sys, "stdout", FakeOutput())
    monkeypatch.setattr(qwen_worker.os, "dup", lambda _descriptor: 9322)
    monkeypatch.setattr(qwen_worker.os, "fdopen", lambda *_args, **_options: protocol)
    monkeypatch.setattr(qwen_worker.os, "dup2", lambda *_args: None)

    qwen_worker.serve(model_path, runtime)

    assert [json.loads(line) for line in protocol.lines] == [
        {"ok": False, "error": "voice"},
        {"ok": True},
    ]
    assert len(loads) == 1 and torch_calls == [4]
    assert writes == [("Supported voice.", supported_destination, "Ryan")]


def test_worker_timeout_cancellation_overflow_and_dead_start_cleanup(tmp_path, monkeypatch):
    async def scenario():
        settings = settings_fixture(tmp_path)
        assets = SpeechAssets(settings.workspace)
        provider = QwenSpeechProvider(settings, assets)
        for response in (None, b"x" * 5000 + b"\n", b"not json\n"):
            worker = FakeWorker(response)
            install_worker(monkeypatch, worker)
            provider._settings = SpeechSettings(
                workspace=settings.workspace,
                model_path=settings.model_path,
                python_executable=sys.executable,
                timeout_seconds=0.02,
            )
            _, destination = assets.allocate()
            with pytest.raises(SpeechError):
                await provider.generate("Source", destination)
            assert worker.returncode is not None and worker.waited and worker.stdin.closed
        worker = FakeWorker(None)
        install_worker(monkeypatch, worker)
        provider._settings = settings
        _, destination = assets.allocate()
        task = asyncio.create_task(provider.generate("Source", destination))
        await worker.started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert worker.returncode is not None and worker.waited
        started = asyncio.Event()

        async def blocked_start():
            started.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(provider, "_start", blocked_start)
        provider._settings = SpeechSettings(timeout_seconds=0.02)
        with pytest.raises(SpeechError) as timeout:
            await provider.generate("Source", destination)
        assert timeout.value.status_code == 504 and started.is_set()

    asyncio.run(scenario())


def test_runtime_probe_is_pinned_and_does_not_import_qwen(monkeypatch):
    versions = {
        "qwen-tts": "0.1.1",
        "torch": "2.10.0",
        "torchaudio": "2.10.0",
        "transformers": "4.57.3",
        "soundfile": "0.14.0",
        "accelerate": "1.12.0",
    }
    monkeypatch.setattr(qwen_worker.importlib.metadata, "version", lambda name: versions[name])
    monkeypatch.setattr(qwen_worker.importlib.util, "find_spec", lambda _name: object())
    assert qwen_worker.probe() == {"available": True}
    versions["torch"] = "2.11.0"
    assert qwen_worker.probe() == {"available": False}
    assert runtime_environment().get("DEEPSEEK_API_KEY") is None
