"""Optional Qwen3-TTS Mac experiment. Heavy imports occur only after platform checks."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import subprocess
import sys
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol
from uuid import uuid4

from qwen3_tts_workspace import checked_child, checked_workspace, runtime_environment

if TYPE_CHECKING:
    from qwen_tts import Qwen3TTSModel

MODEL_ID = "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
MODEL_REVISION = "85e237c12c027371202489a0ec509ded67b5e4b5"
SYNTHETIC_TEXT = "Hello. This is a short English shadowing practice sentence."
VOICE = "Aiden"
MPS_SAMPLE_SECONDS = 0.1


def require_target(system: str, machine: str) -> None:
    if system != "Darwin" or machine != "arm64":
        raise ValueError("This experiment requires native ARM64 macOS.")


def new_run_directory(runtime_dir: Path) -> Path:
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:12]
    run_dir = runtime_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def snapshot_path(workspace: Path, runtime_dir: Path, relative_path: str) -> Path:
    root = runtime_dir.resolve()
    candidate = (root / relative_path).resolve()
    if not candidate.is_relative_to(root / "model-cache"):
        raise ValueError("The model snapshot must be inside this runtime's model-cache.")
    return checked_child(workspace, candidate)


def audio_statistics(samples: Sequence[float], sample_rate: int) -> dict[str, float | int]:
    if isinstance(sample_rate, bool) or not isinstance(sample_rate, int) or sample_rate <= 0:
        raise ValueError("The sample rate must be a positive integer.")
    if not samples:
        raise ValueError("The generated audio is empty.")
    peak = 0.0
    sum_squares = 0.0
    for value in samples:
        if not math.isfinite(value):
            raise ValueError("The generated audio contains non-finite samples.")
        peak = max(peak, abs(value))
        sum_squares += value * value
    if peak == 0:
        raise ValueError("The generated audio is silent.")
    if not math.isfinite(sum_squares):
        raise ValueError("The generated waveform has invalid amplitude statistics.")
    return {
        "sample_rate_hz": sample_rate,
        "sample_count": len(samples),
        "duration_seconds": len(samples) / sample_rate,
        "peak_absolute_amplitude": peak,
        "rms_amplitude": math.sqrt(sum_squares / len(samples)),
    }


@dataclass(frozen=True)
class SpeechAudio:
    samples: Sequence[float]
    sample_rate: int


class SpeechProvider(Protocol):
    """Tiny spike contract; no production runtime or persistence decision is implied."""

    def synthesize(self, text: str, voice: str) -> SpeechAudio: ...


class QwenSpeechProvider:
    def __init__(self, model: Qwen3TTSModel) -> None:
        self._model = model
        speakers = model.get_supported_speakers() or []
        if VOICE.lower() not in {speaker.lower() for speaker in speakers}:
            raise ValueError("The loaded CustomVoice model does not report Aiden support.")

    def synthesize(self, text: str, voice: str) -> SpeechAudio:
        wavs, sample_rate = self._model.generate_custom_voice(
            text=text, language="English", speaker=voice, max_new_tokens=256
        )
        if len(wavs) != 1 or wavs[0].ndim != 1:
            raise ValueError("The provider must return one mono waveform.")
        return SpeechAudio(wavs[0].tolist(), int(sample_rate))


def synthesize_sample(provider: SpeechProvider) -> SpeechAudio:
    audio = provider.synthesize(SYNTHETIC_TEXT, VOICE)
    audio_statistics(audio.samples, audio.sample_rate)
    return audio


def hardware_summary() -> dict[str, str | int]:
    def value(command: list[str]) -> str:
        return subprocess.check_output(command, text=True).strip()

    return {
        "macos_version": value(["sw_vers", "-productVersion"]),
        "architecture": platform.machine(),
        "chip": value(["sysctl", "-n", "machdep.cpu.brand_string"]),
        "physical_memory_bytes": int(value(["sysctl", "-n", "hw.memsize"])),
        "logical_cpu_count": os.cpu_count() or 0,
        "python_version": platform.python_version(),
    }


def package_versions() -> dict[str, str]:
    names = ("qwen-tts", "torch", "torchaudio", "transformers", "accelerate", "soundfile")
    return {name: importlib.metadata.version(name) for name in names}


def write_json(path: Path, value: object) -> None:
    # Exclusive creation prevents overwriting successful evidence from an earlier attempt.
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def prepare(workspace: Path, runtime_dir: Path, uv_version: str) -> None:
    from huggingface_hub import snapshot_download

    lock_path = checked_child(workspace, runtime_dir / "requirements.lock")
    lock_digest = hashlib.sha256(lock_path.read_bytes()).hexdigest()
    started = time.perf_counter()
    model_path = Path(
        snapshot_download(
            repo_id=MODEL_ID,
            revision=MODEL_REVISION,
            cache_dir=checked_child(workspace, runtime_dir / "model-cache"),
            token=False,
            max_workers=4,
        )
    )
    snapshot_relative = str(model_path.relative_to(runtime_dir))
    if not (model_path / "speech_tokenizer" / "config.json").is_file():
        raise ValueError("The snapshot is missing its speech tokenizer.")
    write_json(
        runtime_dir / "preparation.json",
        {
            "model_id": MODEL_ID,
            "model_revision": MODEL_REVISION,
            "snapshot_relative_path": snapshot_relative,
            "download_seconds": time.perf_counter() - started,
            "uv_version": uv_version,
            "requirements_lock_sha256": lock_digest,
            "hardware": hardware_summary(),
            "packages": package_versions(),
        },
    )
    print("Complete model snapshot and preparation.json are ready.")


class MpsMemorySampler:
    def __init__(self, torch_module: object, enabled: bool) -> None:
        self._torch = torch_module
        self._enabled = enabled
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.peak_tensor_bytes = 0
        self.peak_driver_bytes = 0
        self.error_type: str | None = None

    def _capture(self) -> None:
        try:
            self.peak_tensor_bytes = max(
                self.peak_tensor_bytes, self._torch.mps.current_allocated_memory()
            )
            self.peak_driver_bytes = max(
                self.peak_driver_bytes, self._torch.mps.driver_allocated_memory()
            )
        except Exception as error:
            self.error_type = type(error).__name__
            self._stop.set()

    def _sample(self) -> None:
        self._capture()
        while not self._stop.wait(MPS_SAMPLE_SECONDS):
            self._capture()

    def start(self) -> None:
        if self._enabled:
            self._thread = threading.Thread(target=self._sample, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
            self._capture()


def run(workspace: Path, runtime_dir: Path, device: str, mps_cpu_fallback: bool) -> int:
    if mps_cpu_fallback and device != "mps":
        raise ValueError("CPU fallback is only meaningful for an explicit MPS experiment.")
    preparation_path = checked_child(workspace, runtime_dir / "preparation.json")
    preparation = json.loads(preparation_path.read_text(encoding="utf-8"))
    if preparation["model_id"] != MODEL_ID or preparation["model_revision"] != MODEL_REVISION:
        raise ValueError("Prepare the expected frozen CustomVoice snapshot first.")
    model_path = snapshot_path(workspace, runtime_dir, preparation["snapshot_relative_path"])
    checked_child(workspace, runtime_dir / "runs")
    run_dir = new_run_directory(runtime_dir)
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1" if mps_cpu_fallback else "0"
    result: dict[str, object] = {
        "status": "failed",
        "model_id": MODEL_ID,
        "model_revision": MODEL_REVISION,
        "device_requested": device,
        "dtype": "float32",
        "attention_implementation": "eager",
        "mps_cpu_fallback_enabled": mps_cpu_fallback,
        "voice": VOICE,
        "language": "English",
        "synthetic_text": SYNTHETIC_TEXT,
        "seed": 42,
        "max_new_tokens": 256,
        "hardware": preparation["hardware"],
        "packages": preparation["packages"],
        "requirements_lock_sha256": preparation["requirements_lock_sha256"],
        "audio_review": "pending human listening",
    }
    memory: MpsMemorySampler | None = None
    started = time.perf_counter()
    try:
        import resource

        import soundfile
        import torch
        from qwen_tts import Qwen3TTSModel

        result["import_seconds"] = time.perf_counter() - started
        if device == "mps" and not torch.backends.mps.is_available():
            raise RuntimeError("MPS is unavailable on this interpreter/device.")
        memory = MpsMemorySampler(torch, device == "mps")
        memory.start()

        def synchronize() -> None:
            if device == "mps":
                torch.mps.synchronize()

        load_started = time.perf_counter()
        model = Qwen3TTSModel.from_pretrained(
            str(model_path),
            device_map=device,
            dtype=torch.float32,
            attn_implementation="eager",
            local_files_only=True,
            trust_remote_code=False,
        )
        synchronize()
        result["model_load_seconds"] = time.perf_counter() - load_started
        result["model_device_reported"] = str(model.device)
        result["supported_speakers"] = model.get_supported_speakers()
        provider: SpeechProvider = QwenSpeechProvider(model)
        generations: list[dict[str, object]] = []
        result["generations"] = generations
        for label in ("first", "warm"):
            torch.manual_seed(42)
            synchronize()
            generation_started = time.perf_counter()
            audio = synthesize_sample(provider)
            synchronize()
            generation_seconds = time.perf_counter() - generation_started
            statistics = audio_statistics(audio.samples, audio.sample_rate)
            audio_path = run_dir / f"{label}.wav"
            soundfile.write(str(audio_path), audio.samples, audio.sample_rate, subtype="PCM_16")
            generations.append(
                {
                    "label": label,
                    "generation_seconds": generation_seconds,
                    "generation_to_audio_duration_ratio": generation_seconds
                    / statistics["duration_seconds"],
                    "audio_file": audio_path.name,
                    **statistics,
                }
            )
        result["peak_rss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        result["status"] = "generated"
    except Exception as error:
        # Keep full diagnostic paths locally, but put only the exception type in shareable JSON.
        import traceback

        with (run_dir / "failure.log").open("x", encoding="utf-8") as stream:
            traceback.print_exc(file=stream)
        result["error_type"] = type(error).__name__
    finally:
        if memory is not None:
            memory.stop()
            result["mps_memory"] = {
                "sample_interval_seconds": MPS_SAMPLE_SECONDS,
                "sampled_peak_tensor_bytes": memory.peak_tensor_bytes,
                "sampled_peak_driver_bytes": memory.peak_driver_bytes,
                "measurement_error_type": memory.error_type,
            }
        result["total_process_work_seconds"] = time.perf_counter() - started
        write_json(run_dir / "result.json", result)
    print(f"{result['status']}: {run_dir / 'result.json'}")
    return 0 if result["status"] == "generated" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    preparation = commands.add_parser("prepare")
    preparation.add_argument("--workspace-root", required=True)
    preparation.add_argument("--runtime-dir", required=True, type=Path)
    preparation.add_argument("--uv-version", required=True)
    experiment = commands.add_parser("run")
    experiment.add_argument("--workspace-root", required=True)
    experiment.add_argument("--runtime-dir", required=True, type=Path)
    experiment.add_argument("--device", required=True, choices=("cpu", "mps"))
    experiment.add_argument("--mps-cpu-fallback", action="store_true")
    arguments = parser.parse_args()
    try:
        require_target(platform.system(), platform.machine())
        workspace = checked_workspace(arguments.workspace_root)
        runtime_dir = checked_child(workspace, arguments.runtime_dir)
        if not runtime_dir.is_dir():
            raise ValueError("The prepared runtime directory must already exist.")
        os.environ.update(runtime_environment(workspace))
        Path(os.environ["TMPDIR"]).mkdir(parents=True, exist_ok=True)
        if arguments.command == "prepare":
            prepare(workspace, runtime_dir, arguments.uv_version)
            return 0
        return run(workspace, runtime_dir, arguments.device, arguments.mps_cpu_fallback)
    except (ValueError, OSError, KeyError) as error:
        print(f"Spike could not start: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
