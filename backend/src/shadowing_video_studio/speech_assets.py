"""Immutable WAVs; durable registrations may resolve earlier owned sessions."""

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

from shadowing_video_studio.project_store import ProjectError, ProjectStore
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
    project_id: str | None = None
    document_id: str | None = None


class SpeechAssets:
    def __init__(self, workspace: Path, store: ProjectStore | None = None) -> None:
        self.workspace = workspace.resolve()
        self.store = store
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

    def _read_file(self, path: Path, *, registered: bool = False) -> bytes:
        directory = path.parent if registered else self._session()
        if (
            directory.parent != self.workspace / "speech"
            or not OPAQUE_ID.fullmatch(directory.name)
            or not OPAQUE_ID.fullmatch(path.stem)
            or path.suffix != ".wav"
            or path.parent != directory
            or any(
                item.is_symlink() or getattr(item, "is_junction", lambda: False)()
                for item in (path, *path.parents)
            )
            or path.resolve() != path
        ):
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
        project_id: str | None = None,
        document_id: str | None = None,
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
            project_id,
            document_id,
        )
        self._assets[asset_id] = asset
        self._cache[(sentence.id, sentence.text, fingerprint)] = asset_id
        self._bytes -= MAX_WAV_BYTES - len(content)
        return asset

    def _load(self, asset_id: str) -> SpeechAsset:
        if not OPAQUE_ID.fullmatch(asset_id):
            raise SpeechError("Audio asset not found.", 404)
        if asset_id in self._assets:
            return self._assets[asset_id]
        try:
            record = self.store.speech_asset(asset_id) if self.store else None
        except ProjectError as exc:
            raise SpeechError(exc.detail, exc.status_code) from exc
        if not record:
            raise SpeechError("Audio asset not found.", 404)
        session_id = record["sessionId"]
        if not OPAQUE_ID.fullmatch(session_id):
            raise SpeechError("The saved audio registration is invalid.", 404)
        asset = SpeechAsset(
            asset_id,
            record["sentenceId"],
            record["text"],
            record["fingerprint"],
            record["durationSeconds"],
            self.workspace / "speech" / session_id / f"{asset_id}.wav",
            record["sizeBytes"],
            record["sha256"],
            record["voice"],
            record["projectId"],
            record["documentId"],
        )
        self._assets[asset_id] = asset
        return asset

    def read(self, asset_id: str) -> bytes:
        asset = self._load(asset_id)
        try:
            content = self._read_file(asset.path, registered=True)
            if (
                len(content) != asset.size_bytes
                or hashlib.sha256(content).hexdigest() != asset.sha256
            ):
                raise SpeechError("The audio asset changed. Generate speech again.", 404)
            with wave.open(io.BytesIO(content), "rb") as wav:
                frames = wav.getnframes()
                if (
                    wav.getnchannels() != 1
                    or wav.getframerate() != 24000
                    or wav.getsampwidth() != 2
                    or wav.getcomptype() != "NONE"
                    or not 0 < frames <= MAX_WAV_SECONDS * 24000
                    or len(wav.readframes(frames)) != frames * 2
                    or abs(frames / 24000 - asset.duration_seconds) > 1 / 24000
                ):
                    raise SpeechError("The saved audio format is invalid.", 404)
            return content
        except (OSError, wave.Error, EOFError, ValueError) as exc:
            raise SpeechError("The audio asset is no longer available.", 404) from exc

    def match(
        self,
        asset_id: str,
        sentence: SpeechSentence,
        fingerprint: str,
        voice: str = VOICE,
        project_id: str | None = None,
        document_id: str | None = None,
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
        if project_id is not None and (asset.project_id, asset.document_id) != (
            project_id,
            document_id,
        ):
            raise SpeechError("Audio belongs to a different project or document.", 409)
        return asset

    def reusable(
        self,
        sentence: SpeechSentence,
        fingerprint: str,
        voice: str = VOICE,
        project_id: str | None = None,
        document_id: str | None = None,
    ) -> SpeechAsset | None:
        if project_id is not None:
            if not self.store or not document_id:
                return None
            try:
                records = self.store.speech_candidates(
                    project_id, document_id, sentence.id, sentence.text, fingerprint, voice
                )
            except ProjectError as exc:
                raise SpeechError(exc.detail, exc.status_code) from exc
            for record in records:
                try:
                    return self.match(
                        record["id"], sentence, fingerprint, voice, project_id, document_id
                    )
                except SpeechError:
                    continue
            return None
        asset_id = self._cache.get((sentence.id, sentence.text, fingerprint))
        if not asset_id:
            return None
        try:
            return self.match(asset_id, sentence, fingerprint, voice)
        except SpeechError:
            return None


def flush_media(path: Path) -> None:
    """The registration transaction must never precede durable media bytes."""
    # Windows FlushFileBuffers requires a writable handle; POSIX permits read-only fsync.
    flags = os.O_RDWR if os.name == "nt" else os.O_RDONLY
    descriptor = os.open(path, flags | getattr(os, "O_NOFOLLOW", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    if os.name != "nt":
        descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
