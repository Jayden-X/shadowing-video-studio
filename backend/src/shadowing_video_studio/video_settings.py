"""Server-only video tool configuration; readiness never installs or encodes media."""

import asyncio
import math
import os
import shutil
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Self

from shadowing_video_studio.providers.process import ProcessResult, SubprocessRunner
from shadowing_video_studio.text_processing import PreparationError
from shadowing_video_studio.video_rendering import VideoRenderingError

REQUIRED_FILTERS = frozenset(
    {
        "drawtext",
        "showwaves",
        "overlay",
        "color",
        "aresample",
        "aformat",
        "apad",
        "atrim",
        "asetpts",
        "asplit",
        "drawbox",
        "fps",
        "format",
    }
)
REQUIRED_ENCODERS = frozenset({"libx264", "pcm_s16le", "aac"})
REQUIRED_MUXERS = frozenset({"mp4", "matroska"})
REQUIRED_DRAWTEXT_OPTIONS = frozenset(
    {"fontfile", "textfile", "expansion", "fontsize", "fontcolor", "x", "y", "line_spacing"}
)
TOOL_PROBE_TIMEOUT_SECONDS = 10


class CapabilityProcessRunner(Protocol):
    async def run(
        self,
        arguments: Sequence[str],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        timeout: float,
    ) -> ProcessResult: ...


def _executable_fingerprint(path: Path) -> tuple[str, int, int, int, int, int]:
    info = path.stat()
    return (
        str(path),
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _listed_names(output: bytes) -> set[str]:
    names = set()
    for line in output.decode("utf-8").splitlines():
        columns = line.split()
        if (
            len(columns) >= 2
            and 1 <= len(columns[0]) <= 6
            and all(char == "." or "A" <= char <= "Z" for char in columns[0])
        ):
            names.update(columns[1].split(","))
    return names


class VideoToolPreflight:
    """Probe fixed-template capabilities once per unchanged executable pair.

    Listing capabilities does not encode or invoke the model. Only successful probes
    are cached; changed binaries or corrected configuration are checked again.
    """

    def __init__(self, runner: CapabilityProcessRunner | None = None) -> None:
        self.runner = runner or SubprocessRunner()
        self._lock = asyncio.Lock()
        self._validated_fingerprint: tuple | None = None
        self.supports_text_shaping = False

    async def validate(self, ffmpeg: Path, ffprobe: Path, workspace: Path) -> None:
        async with self._lock:
            fingerprint = (_executable_fingerprint(ffmpeg), _executable_fingerprint(ffprobe))
            if fingerprint == self._validated_fingerprint:
                return
            environment = {
                "PATH": os.defpath,
                "LANG": "C",
                "LC_ALL": "C",
                "HOME": str(workspace),
                "TMPDIR": str(workspace),
                "XDG_CACHE_HOME": str(workspace),
            }
            try:
                async with asyncio.timeout(TOOL_PROBE_TIMEOUT_SECONDS):
                    for option, required, kind in (
                        ("-filters", REQUIRED_FILTERS, "filters"),
                        ("-encoders", REQUIRED_ENCODERS, "encoders"),
                        ("-muxers", REQUIRED_MUXERS, "muxers"),
                    ):
                        result = await self.runner.run(
                            [str(ffmpeg), "-nostdin", "-hide_banner", option],
                            cwd=workspace,
                            environment=environment,
                            timeout=TOOL_PROBE_TIMEOUT_SECONDS,
                        )
                        if result.returncode:
                            raise VideoRenderingError(
                                "Could not check FFmpeg capabilities. Configure working local "
                                "FFmpeg and ffprobe executables.",
                                "unavailable",
                            )
                        missing = required - _listed_names(result.stdout)
                        if missing:
                            raise VideoRenderingError(
                                f"Required FFmpeg {kind} are missing "
                                f"({', '.join(sorted(missing))}). "
                                "Set VIDEO_FFMPEG_EXECUTABLE to a complete FFmpeg build "
                                "including drawtext, libx264 and AAC.",
                                "unavailable",
                            )
                    result = await self.runner.run(
                        [str(ffmpeg), "-nostdin", "-hide_banner", "-h", "filter=drawtext"],
                        cwd=workspace,
                        environment=environment,
                        timeout=TOOL_PROBE_TIMEOUT_SECONDS,
                    )
                    options = {
                        columns[0]
                        for line in result.stdout.decode("utf-8").splitlines()
                        if len(columns := line.split()) >= 2
                        and columns[1].startswith("<")
                        and columns[1].endswith(">")
                    }
                    missing = REQUIRED_DRAWTEXT_OPTIONS - options
                    if result.returncode or missing:
                        raise VideoRenderingError(
                            "The configured FFmpeg drawtext filter lacks required template "
                            "options. Set VIDEO_FFMPEG_EXECUTABLE to a complete FFmpeg build.",
                            "unavailable",
                        )
                    supports_text_shaping = "text_shaping" in options
                    result = await self.runner.run(
                        [str(ffprobe), "-hide_banner", "-version"],
                        cwd=workspace,
                        environment=environment,
                        timeout=TOOL_PROBE_TIMEOUT_SECONDS,
                    )
                    if result.returncode or not result.stdout.startswith(b"ffprobe version "):
                        raise VideoRenderingError(
                            "Set VIDEO_FFPROBE_EXECUTABLE to a working local ffprobe executable.",
                            "unavailable",
                        )
            except (OSError, TimeoutError, PreparationError, UnicodeError) as exc:
                raise VideoRenderingError(
                    "Could not check the local video tools. Configure working FFmpeg and "
                    "ffprobe executables and retry.",
                    "unavailable",
                ) from exc
            if fingerprint != (
                _executable_fingerprint(ffmpeg),
                _executable_fingerprint(ffprobe),
            ):
                raise VideoRenderingError(
                    "The configured video tools changed during their check. Retry.", "unavailable"
                )
            self.supports_text_shaping = supports_text_shaping
            self._validated_fingerprint = fingerprint


@dataclass(frozen=True)
class VideoSettings:
    ffmpeg_executable: Path | None = None
    ffprobe_executable: Path | None = None
    font_path: Path | None = None
    timeout_seconds: float = 600
    error: str | None = None

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] | None = None) -> Self:
        values = os.environ if environment is None else environment
        error = None
        try:
            timeout = float(values.get("VIDEO_TIMEOUT_SECONDS", "600"))
            if not math.isfinite(timeout) or not 30 <= timeout <= 3600:
                raise ValueError
        except ValueError:
            timeout = 600
            error = "Set VIDEO_TIMEOUT_SECONDS between 30 and 3600."
        ffmpeg = values.get("VIDEO_FFMPEG_EXECUTABLE", "").strip() or shutil.which("ffmpeg")
        ffprobe = values.get("VIDEO_FFPROBE_EXECUTABLE", "").strip() or shutil.which("ffprobe")
        font = values.get("VIDEO_FONT_PATH", "").strip()
        if not font and sys.platform == "darwin":
            font = "/System/Library/Fonts/Supplemental/Arial.ttf"
        return cls(
            Path(ffmpeg) if ffmpeg else None,
            Path(ffprobe) if ffprobe else None,
            Path(font) if font else None,
            timeout,
            error,
        )

    def validated_paths(self) -> tuple[Path, Path, Path]:
        if self.error:
            raise VideoRenderingError(self.error, "unavailable")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (float, int))
            or not math.isfinite(self.timeout_seconds)
            or not 30 <= self.timeout_seconds <= 3600
        ):
            raise VideoRenderingError(
                "Set VIDEO_TIMEOUT_SECONDS between 30 and 3600.", "unavailable"
            )
        for executable, key in (
            (self.ffmpeg_executable, "VIDEO_FFMPEG_EXECUTABLE"),
            (self.ffprobe_executable, "VIDEO_FFPROBE_EXECUTABLE"),
        ):
            if (
                not executable
                or not executable.is_absolute()
                or not executable.is_file()
                or executable.suffix.lower() in {".cmd", ".bat", ".ps1"}
                or not os.access(executable, os.X_OK)
            ):
                raise VideoRenderingError(
                    f"Set {key} to an existing local executable.", "unavailable"
                )
        font = self.font_path
        if (
            not font
            or not font.is_absolute()
            or not font.is_file()
            or not 0 < font.stat().st_size <= 16 * 1024 * 1024
            or any(
                item.is_symlink() or getattr(item, "is_junction", lambda: False)()
                for item in (font, *font.parents)
            )
        ):
            raise VideoRenderingError(
                "Set VIDEO_FONT_PATH to a real local Unicode TrueType/OpenType font.", "unavailable"
            )
        assert self.ffmpeg_executable and self.ffprobe_executable
        return self.ffmpeg_executable.resolve(), self.ffprobe_executable.resolve(), font.resolve()
