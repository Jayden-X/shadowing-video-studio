"""Explicit server-only paths; no installation/download or backend substitution."""

import hashlib
import json
import math
import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from shadowing_video_studio.speech import SpeechError

MAX_NEW_TOKENS = 4096
MODEL_REVISION = "85e237c12c027371202489a0ec509ded67b5e4b5"


@dataclass(frozen=True)
class SpeechSettings:
    workspace: Path | None = None
    model_path: Path | None = None
    python_executable: str = sys.executable
    timeout_seconds: float = 600
    error: str | None = None

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] | None = None) -> Self:
        values = os.environ if environment is None else environment
        workspace = values.get("SPEECH_WORKSPACE", "").strip()
        model = values.get("SPEECH_MODEL_PATH", "").strip()
        error = None
        try:
            timeout = float(values.get("SPEECH_TIMEOUT_SECONDS", "600"))
            if not math.isfinite(timeout) or not 30 <= timeout <= 1800:
                raise ValueError
        except ValueError:
            timeout = 600
            error = "Set SPEECH_TIMEOUT_SECONDS between 30 and 1800."
        return cls(
            workspace=Path(workspace) if workspace else None,
            model_path=Path(model) if model else None,
            python_executable=values.get("SPEECH_PYTHON_EXECUTABLE", "").strip() or sys.executable,
            timeout_seconds=timeout,
            error=error,
        )

    def validated_paths(self) -> tuple[Path, Path]:
        if self.error:
            raise SpeechError(self.error, 503)
        if not self.workspace or not self.workspace.is_absolute() or not self.workspace.is_dir():
            raise SpeechError(
                "Set SPEECH_WORKSPACE to an existing absolute runtime directory.", 503
            )
        workspace = self.workspace.resolve()
        if self.workspace.is_symlink() or workspace != self.workspace.absolute():
            raise SpeechError("Use a real speech workspace directory without symbolic links.", 503)
        model = self.model_path
        if not model or not model.is_absolute() or not model.is_dir():
            raise SpeechError("Set SPEECH_MODEL_PATH to the frozen local 0.6B model snapshot.", 503)
        model = model.resolve()
        if not re.fullmatch(r"[0-9a-f]{40}", model.name) or model.name != MODEL_REVISION:
            raise SpeechError(
                "Use the approved frozen 0.6B snapshot revision from the speech runtime guide.", 503
            )
        try:
            config_path = model / "config.json"
            if config_path.stat().st_size > 1024 * 1024:
                raise ValueError
            config = json.loads(config_path.read_bytes())
            if (
                config.get("model_type") != "qwen3_tts"
                or config.get("tts_model_type") != "custom_voice"
                or config.get("tts_model_size") != "0b6"
                or not (model / "model.safetensors").is_file()
                or not (model / "speech_tokenizer" / "model.safetensors").is_file()
            ):
                raise ValueError
        except (OSError, ValueError, AttributeError, TypeError, RecursionError) as exc:
            raise SpeechError(
                "The local 0.6B CustomVoice snapshot is incomplete or invalid.", 503
            ) from exc
        if workspace == model or workspace.is_relative_to(model) or model.is_relative_to(workspace):
            raise SpeechError(
                "Keep the speech workspace separate from the read-only model cache.", 503
            )
        return workspace, model

    def fingerprint(self) -> str:
        # Frozen revision + configuration, not private text or client-supplied identity.
        payload = {
            "adapter": "qwen-cpu-v1",
            "model": str(self.model_path),
            "runtime": self.python_executable,
            "voice": "Aiden",
            "language": "English",
            "backend": "cpu",
            "dtype": "float32",
            "attention": "eager",
            "max_new_tokens": MAX_NEW_TOKENS,
            "non_streaming_mode": True,
            "qwen_tts": "0.1.1",
            "torch": "2.10.0",
            "torchaudio": "2.10.0",
            "cpu_threads": 4,
            "transformers": "4.57.3",
            "accelerate": "1.12.0",
            "soundfile": "0.14.0",
            "revision": MODEL_REVISION,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
