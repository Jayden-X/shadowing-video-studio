"""Project-owned speech types, frozen bindings and one local heavy-job gate."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

MAX_SPEECH_SENTENCES = 100
MAX_SPEECH_TEXT = 4_000
MAX_SPEECH_TOTAL_TEXT = 20_000
MAX_WAV_BYTES = 32 * 1024 * 1024
MAX_WAV_SECONDS = 360
MAX_SESSION_BYTES = 1024 * 1024 * 1024
MAX_SESSION_JOBS = 100
MODEL_NAME = "Qwen3-TTS-12Hz-0.6B-CustomVoice"
VOICE = "Aiden"


class SpeechError(Exception):
    def __init__(self, detail: str, status_code: int = 502) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


@dataclass(frozen=True)
class SpeechReadiness:
    available: bool
    reason: str | None = None
    voice: str = VOICE
    model: str = MODEL_NAME
    backend: str = "cpu"


@dataclass(frozen=True)
class SpeechSentence:
    id: str
    text: str


@dataclass(frozen=True)
class SpeechVoice:
    id: str
    label: str
    configuration_fingerprint: str


@dataclass(frozen=True)
class SpeechCapabilities:
    available: bool
    reason: str | None = None
    voices: tuple[SpeechVoice, ...] = ()
    default_voice: str | None = None
    model: str = MODEL_NAME
    language: str = "English"


class SpeechProvider(Protocol):
    @property
    def fingerprint(self) -> str: ...

    async def readiness(self) -> SpeechReadiness: ...

    async def capabilities(self) -> SpeechCapabilities: ...

    def fingerprint_for_voice(self, voice: str) -> str: ...

    async def generate(self, text: str, destination: Path, voice: str = VOICE) -> None: ...

    async def close(self) -> None: ...


class HeavyJobGate:
    """Shared by speech and the later renderer within this single service process.

    Claims happen synchronously before scheduling/awaiting any work. This is not a
    cross-process or durable lock; the local launcher must use one ASGI worker.
    """

    def __init__(self) -> None:
        self._owner: str | None = None

    def claim(self, owner: str) -> bool:
        if self._owner is not None:
            return False
        self._owner = owner
        return True

    def release(self, owner: str) -> None:
        if self._owner == owner:
            self._owner = None

    @property
    def busy(self) -> bool:
        return self._owner is not None
