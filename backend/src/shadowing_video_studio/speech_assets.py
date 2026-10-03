"""WAVs live in a unique session directory; only volatile metadata binds assets."""

import hashlib
import io
import os
import re
import shutil
import stat
import uuid
import wave
from dataclasses import dataclass
from pathlib import Path

from shadowing_video_studio.speech import (
    MAX_SESSION_BYTES,
    MAX_WAV_BYTES,
    MAX_WAV_SECONDS,
    VOICE,
    SpeechError,
    SpeechSentence,
)

OPAQUE_ID = re.compile(r"[0-9a-f]{32}")


@dataclass(frozen=True)
class SpeechAsset:
    id: str
    sentence_id: str
    text: str
    fingerprint: str
    duration_seconds: float
    path: Path
    size_bytes: int
    sha256: str
    voice: str = VOICE


class SpeechAssets:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        self._directory: Path | None = None
        self._assets: dict[str, SpeechAsset] = {}
        self._cache: dict[tuple[str, str, str], str] = {}
        self._bytes = 0

    def _session(self) -> Path:
        if self._directory is None:
            # mkdir exclusive ownership; do not delete or overwrite earlier sessions.
            parent = self.workspace / "speech"
            if parent.exists() and (parent.is_symlink() or parent.resolve() != parent):
                raise SpeechError(
                    "The speech asset directory is unsafe. Check its configuration.", 503
                )
            parent.mkdir(mode=0o700, exist_ok=True)
            directory = parent / uuid.uuid4().hex
            directory.mkdir(mode=0o700)
            self._directory = directory
        directory = self._directory
        if directory.is_symlink() or directory.resolve() != directory:
            raise SpeechError("The speech asset directory changed. Restart after checking it.", 503)
        if not directory.is_relative_to(self.workspace):
            raise SpeechError("The speech asset directory is outside its workspace.", 503)
        return directory

    def runtime_directory(self) -> Path:
        directory = self._session() / "runtime"
        if directory.exists() and (directory.is_symlink() or directory.resolve() != directory):
            raise SpeechError("The speech runtime directory is unsafe.", 503)
        directory.mkdir(mode=0o700, exist_ok=True)
        return directory

    def allocate(self) -> tuple[str, Path]:
        if self._bytes + MAX_WAV_BYTES > MAX_SESSION_BYTES:
            raise SpeechError("Speech session storage is full. Start a new service session.", 409)
        directory = self._session()
        if shutil.disk_usage(directory).free < MAX_WAV_BYTES:
            raise SpeechError("Free disk space before generating more speech.", 409)
        asset_id = uuid.uuid4().hex
        destination = directory / f"{asset_id}.wav"
        if destination.exists():
            raise SpeechError("Could not reserve a new audio asset. Try again.")
        # Reserve the maximum even on failure. Failed/partial files are preserved
        # and must not bypass the session's disk ceiling through repeated retries.
        self._bytes += MAX_WAV_BYTES
        return asset_id, destination

    def _read_file(self, path: Path) -> bytes:
        directory = self._session()
        if path.parent != directory or path.is_symlink() or path.resolve() != path:
            raise SpeechError("The audio asset is no longer available.", 404)
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or not 44 <= info.st_size <= MAX_WAV_BYTES:
                raise SpeechError("The generated audio asset is invalid.")
            content = handle.read(MAX_WAV_BYTES + 1)
        if len(content) != info.st_size or len(content) > MAX_WAV_BYTES:
            raise SpeechError("The generated audio asset changed or exceeded its size limit.")
        return content

    def register(
        self,
        asset_id: str,
        sentence: SpeechSentence,
        fingerprint: str,
        path: Path,
        voice: str = VOICE,
    ) -> SpeechAsset:
        if (
            not OPAQUE_ID.fullmatch(asset_id)
            or asset_id in self._assets
            or path.name != f"{asset_id}.wav"
        ):
            raise SpeechError("Could not register a unique speech asset.")
        content = self._read_file(path)
        try:
            with wave.open(io.BytesIO(content), "rb") as wav:
                frames = wav.getnframes()
                if (
                    wav.getnchannels() != 1
                    or wav.getframerate() != 24000
                    or wav.getsampwidth() != 2
                    or wav.getcomptype() != "NONE"
                    or not 0 < frames <= MAX_WAV_SECONDS * 24000
                    or len(wav.readframes(frames)) != frames * 2
                ):
                    raise ValueError
                duration = frames / 24000
        except (wave.Error, EOFError, ValueError) as exc:
            raise SpeechError("The generated WAV is invalid. Try a shorter sentence.") from exc
        asset = SpeechAsset(
            asset_id,
            sentence.id,
            sentence.text,
            fingerprint,
            duration,
            path,
            len(content),
            hashlib.sha256(content).hexdigest(),
            voice,
        )
        self._assets[asset_id] = asset
        self._cache[(sentence.id, sentence.text, fingerprint)] = asset_id
        self._bytes -= MAX_WAV_BYTES - len(content)
        return asset

    def read(self, asset_id: str) -> bytes:
        if not OPAQUE_ID.fullmatch(asset_id) or asset_id not in self._assets:
            raise SpeechError("Audio asset not found in this service session.", 404)
        asset = self._assets[asset_id]
        try:
            content = self._read_file(asset.path)
            if hashlib.sha256(content).hexdigest() != asset.sha256:
                raise SpeechError("The audio asset changed. Generate speech again.", 404)
            return content
        except OSError as exc:
            raise SpeechError("The audio asset is no longer available.", 404) from exc

    def match(
        self, asset_id: str, sentence: SpeechSentence, fingerprint: str, voice: str = VOICE
    ) -> SpeechAsset:
        """Later rendering must validate the exact frozen ID/text/config binding."""
        self.read(asset_id)
        asset = self._assets[asset_id]
        if (asset.sentence_id, asset.text, asset.fingerprint, asset.voice) != (
            sentence.id,
            sentence.text,
            fingerprint,
            voice,
        ):
            raise SpeechError(
                "Audio no longer matches the reviewed sentence. Generate it again.", 409
            )
        return asset

    def reusable(
        self, sentence: SpeechSentence, fingerprint: str, voice: str = VOICE
    ) -> SpeechAsset | None:
        asset_id = self._cache.get((sentence.id, sentence.text, fingerprint))
        if not asset_id:
            return None
        try:
            return self.match(asset_id, sentence, fingerprint, voice)
        except SpeechError:
            return None
