"""Frozen video attempts share speech's heavy-job gate and preserve prior exports."""

import asyncio
import hashlib
import math
import os
import shutil
import stat
import uuid
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

from shadowing_video_studio.providers.ffmpeg import FfmpegVideoRenderer
from shadowing_video_studio.speech import SpeechError, SpeechSentence
from shadowing_video_studio.speech_assets import OPAQUE_ID, SpeechAsset
from shadowing_video_studio.speech_jobs import SpeechJobs, validate_sentences
from shadowing_video_studio.video_rendering import (
    MAX_VIDEO_ASSET_BYTES,
    MAX_VIDEO_JOB_BYTES,
    FrozenVideoSentence,
    RenderedVideo,
    VideoRenderer,
    VideoRenderingError,
    video_timeline,
)
from shadowing_video_studio.video_settings import VideoSettings, VideoToolPreflight

MAX_VIDEO_JOBS = 20
MAX_VIDEO_INPUT_BYTES = 64 * 1024 * 1024
MAX_VIDEO_SESSION_BYTES = 2 * 1024 * 1024 * 1024
MAX_VIDEO_SECONDS = 600


class VideoJobError(Exception):
    def __init__(self, detail: str, status_code: int = 502) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


@dataclass(frozen=True)
class VideoSentenceSelection:
    id: str
    text: str
    asset_id: str


@dataclass(frozen=True)
class VideoAsset:
    id: str
    job_id: str
    path: Path
    size_bytes: int
    sha256: str
    duration_seconds: float


def checked_directory(path: Path, workspace: Path) -> Path:
    if (
        not path.is_absolute()
        or not path.is_relative_to(workspace)
        or any(
            item.is_symlink() or getattr(item, "is_junction", lambda: False)()
            for item in (path, *path.parents)
        )
        or (path.exists() and not path.is_dir())
    ):
        raise VideoJobError("The video workspace is unsafe. Check its configuration.", 503)
    return path


def file_digest(path: Path, maximum: int) -> tuple[int, str]:
    digest = hashlib.sha256()
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= maximum:
            raise VideoJobError("The video asset is invalid or exceeds its size limit.", 404)
        count = 0
        while chunk := handle.read(1024 * 1024):
            count += len(chunk)
            if count > maximum:
                raise VideoJobError("The video asset changed or exceeded its size limit.", 404)
            digest.update(chunk)
        if count != info.st_size:
            raise VideoJobError("The video asset changed. Export it again.", 404)
    return count, digest.hexdigest()


class VideoJobs:
    def __init__(
        self,
        settings: VideoSettings,
        speech: SpeechJobs,
        renderer: VideoRenderer | None = None,
        tool_preflight: VideoToolPreflight | None = None,
    ) -> None:
        self.settings = settings
        self.speech = speech
        self.gate = speech.gate
        self.renderer = renderer
        self._tool_preflight = tool_preflight or VideoToolPreflight()
        self._jobs: dict[str, dict] = {}
        self._assets: dict[str, VideoAsset] = {}
        self._task: asyncio.Task | None = None
        self._closed = False
        self._reserved_bytes = 0

    async def readiness(self) -> dict:
        try:
            ffmpeg, ffprobe, _ = self.settings.validated_paths()
            if not self.speech.assets:
                raise VideoJobError("Configure the speech workspace before exporting video.", 503)
            workspace = self.speech.assets.workspace
            checked_directory(workspace, workspace)
            if not workspace.is_dir():
                raise VideoJobError("The configured media workspace is unavailable.", 503)
            checked_directory(workspace / "video", workspace)
            await self._tool_preflight.validate(ffmpeg, ffprobe, workspace)
            return {"available": True, "reason": None}
        except (VideoRenderingError, VideoJobError) as exc:
            return {"available": False, "reason": str(exc)}
        except (OSError, ValueError):
            return {
                "available": False,
                "reason": "Check the configured local video tools and workspace.",
            }

    async def submit(self, selections: list[VideoSentenceSelection]) -> dict:
        if self._closed:
            raise VideoJobError("Video service is stopping. Restart before submitting work.", 503)
        if (
            len(self._jobs) >= MAX_VIDEO_JOBS
            or self._reserved_bytes + MAX_VIDEO_JOB_BYTES > MAX_VIDEO_SESSION_BYTES
        ):
            raise VideoJobError(
                "This video session has reached its resource limit. Restart to continue.", 409
            )
        validate_sentences([SpeechSentence(item.id, item.text) for item in selections], False)
        if not self.speech.assets:
            raise VideoJobError("Configure speech and generate the current sentences first.", 503)
        fingerprint = self.speech.provider.fingerprint
        matched: tuple[SpeechAsset, ...] = tuple(
            self.speech.assets.match(item.asset_id, SpeechSentence(item.id, item.text), fingerprint)
            for item in selections
        )
        frozen = tuple(
            FrozenVideoSentence(asset.sentence_id, asset.text, asset.path, asset.duration_seconds)
            for asset in matched
        )
        try:
            pages = video_timeline(frozen)
        except VideoRenderingError as exc:
            raise VideoJobError(
                "Split unusually long sentences before exporting video.", 422
            ) from exc
        if (
            sum(asset.size_bytes for asset in matched) > MAX_VIDEO_INPUT_BYTES
            or sum(page.duration_seconds for page in pages) > MAX_VIDEO_SECONDS
        ):
            raise VideoJobError(
                "Export a shorter video: up to ten minutes and 64 MiB of speech audio.", 422
            )
        job_id = uuid.uuid4().hex
        if not self.gate.claim(job_id):
            raise VideoJobError("A local media job is already running. Wait for it to finish.", 409)
        try:
            readiness = await self.readiness()
            if not readiness["available"]:
                raise VideoJobError(readiness["reason"], 503)
            ffmpeg, ffprobe, font = self.settings.validated_paths()
            renderer = self.renderer or FfmpegVideoRenderer(
                ffmpeg,
                ffprobe,
                font,
                self.settings.timeout_seconds,
                output_budget_bytes=MAX_VIDEO_JOB_BYTES
                - sum(asset.size_bytes for asset in matched),
                supports_text_shaping=self._tool_preflight.supports_text_shaping,
            )
            workspace = self.speech.assets.workspace
            parent = checked_directory(workspace / "video", workspace)
            parent.mkdir(mode=0o700, exist_ok=True)
            if shutil.disk_usage(parent).free < MAX_VIDEO_JOB_BYTES:
                raise VideoJobError("Free disk space before exporting more video.", 409)
            directory = checked_directory(parent / job_id, workspace)
            directory.mkdir(mode=0o700)
            self._reserved_bytes += MAX_VIDEO_JOB_BYTES
            job = {
                "id": job_id,
                "status": "queued",
                "completedSentences": 0,
                "totalSentences": len(matched),
                "assetId": None,
                "durationSeconds": None,
                "error": None,
            }
            self._jobs[job_id] = job
            self._task = asyncio.create_task(self._run(job, matched, directory, renderer))
            return deepcopy(job)
        except (OSError, ValueError) as exc:
            self.gate.release(job_id)
            raise VideoJobError(
                "Could not prepare a safe video output directory. Check configuration.", 503
            ) from exc
        except BaseException:
            self.gate.release(job_id)
            raise

    async def _run(
        self, job: dict, matched: tuple[SpeechAsset, ...], directory: Path, renderer: VideoRenderer
    ) -> None:
        job["status"] = "running"
        try:
            assert self.speech.assets is not None
            frozen = []
            for index, asset in enumerate(matched, 1):
                content = self.speech.assets.read(asset.id)
                snapshot = directory / f"input-{index:04d}.wav"
                with snapshot.open("xb") as handle:
                    handle.write(content)
                frozen.append(
                    FrozenVideoSentence(
                        asset.sentence_id, asset.text, snapshot, asset.duration_seconds
                    )
                )
            render_directory = checked_directory(directory / "render", self.speech.assets.workspace)
            render_directory.mkdir(mode=0o700)

            def progress(completed: int, total: int) -> None:
                if (
                    total == job["totalSentences"]
                    and job["completedSentences"] <= completed <= total
                ):
                    job["completedSentences"] = completed

            result = await renderer.render(tuple(frozen), render_directory, on_progress=progress)
            expected = sum(page.duration_seconds for page in video_timeline(frozen))
            asset, stored = await asyncio.to_thread(
                self._register, job["id"], result, directory, expected
            )
            if asset.id in self._assets:
                raise VideoJobError("Could not register a unique video asset. Retry the export.")
            self._assets[asset.id] = asset
            self._reserved_bytes -= MAX_VIDEO_JOB_BYTES - stored
            job.update(
                status="completed",
                completedSentences=job["totalSentences"],
                assetId=asset.id,
                durationSeconds=asset.duration_seconds,
            )
        except asyncio.CancelledError:
            job.update(
                status="failed",
                error="Video rendering stopped. Speech and earlier exports are preserved.",
            )
            raise
        except VideoRenderingError as exc:
            job.update(status="failed", error=exc.message)
        except SpeechError as exc:
            job.update(status="failed", error=exc.detail)
        except VideoJobError as exc:
            job.update(status="failed", error=exc.detail)
        except Exception:
            job.update(
                status="failed",
                error="Video rendering failed. Speech and earlier exports are preserved; "
                "retry the export.",
            )
        finally:
            self.gate.release(job["id"])

    def _register(
        self, job_id: str, result: RenderedVideo, directory: Path, expected: float
    ) -> tuple[VideoAsset, int]:
        if (
            result.path != directory / "render" / "video.mp4"
            or not math.isfinite(result.duration_seconds)
            or result.duration_seconds <= 0
            or abs(result.duration_seconds - expected) > 0.25
            or (result.width, result.height, result.frame_rate) != (1920, 1080, 30)
        ):
            raise VideoJobError("The rendered video did not match the frozen timeline.")
        self._checked_asset_path(result.path, job_id)
        size, digest = file_digest(result.path, MAX_VIDEO_ASSET_BYTES)
        stored = 0
        for parent, directories, files in os.walk(directory, followlinks=False):
            for name in directories:
                checked_directory(Path(parent) / name, self.speech.assets.workspace)
            for name in files:
                path = Path(parent) / name
                if path.is_symlink() or not path.is_file():
                    raise VideoJobError("The video job produced an unsafe file.")
                stored += path.stat().st_size
                if stored > MAX_VIDEO_JOB_BYTES:
                    raise VideoJobError(
                        "The video exceeded its resource limit. Export fewer sentences."
                    )
        asset = VideoAsset(
            uuid.uuid4().hex, job_id, result.path, size, digest, result.duration_seconds
        )
        return asset, stored

    def _checked_asset_path(self, path: Path, job_id: str) -> None:
        if (
            not self.speech.assets
            or path != self.speech.assets.workspace / "video" / job_id / "render" / "video.mp4"
        ):
            raise VideoJobError("Video asset not found in this service session.", 404)
        checked_directory(path.parent, self.speech.assets.workspace)
        if path.is_symlink() or not path.is_file() or path.resolve() != path:
            raise VideoJobError("The video asset is no longer available.", 404)

    def get(self, job_id: str) -> dict:
        if not OPAQUE_ID.fullmatch(job_id) or job_id not in self._jobs:
            raise VideoJobError("Video job not found in this service session.", 404)
        return deepcopy(self._jobs[job_id])

    def asset(self, asset_id: str) -> VideoAsset:
        if not OPAQUE_ID.fullmatch(asset_id) or asset_id not in self._assets:
            raise VideoJobError("Video asset not found in this service session.", 404)
        asset = self._assets[asset_id]
        try:
            self._checked_asset_path(asset.path, asset.job_id)
            if file_digest(asset.path, MAX_VIDEO_ASSET_BYTES) != (asset.size_bytes, asset.sha256):
                raise VideoJobError("The video asset changed. Export it again.", 404)
            return asset
        except OSError as exc:
            raise VideoJobError("The video asset is no longer available.", 404) from exc

    async def wait(self) -> None:
        if self._task:
            await self._task

    async def close(self) -> None:
        self._closed = True
        if self._task and not self._task.done():
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
