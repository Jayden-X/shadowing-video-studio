"""Validate a bounded static raster with the existing local FFmpeg tools."""

import asyncio
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

from shadowing_video_studio.providers.process import ProcessResult, SubprocessRunner
from shadowing_video_studio.text_processing import PreparationError
from shadowing_video_studio.visual_assets import (
    IMAGE_VALIDATION_SECONDS,
    VisualAssetError,
    validate_dimensions,
)

EXPECTED_CODECS = {"image/png": "png", "image/jpeg": "mjpeg", "image/webp": "webp"}
MAX_DECODER_ALLOCATION = 128 * 1024 * 1024


class ImageProcessRunner(Protocol):
    async def run(
        self,
        arguments: Sequence[str],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        timeout: float,
    ) -> ProcessResult: ...


class ImageProbe:
    def __init__(
        self,
        ffmpeg: Path,
        ffprobe: Path,
        runner: ImageProcessRunner | None = None,
    ) -> None:
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self.runner = runner or SubprocessRunner()

    async def validate(self, path: Path, mime_type: str) -> tuple[int, int]:
        if mime_type not in EXPECTED_CODECS or not path.is_absolute():
            raise VisualAssetError("Use a supported local image.")
        environment = {
            "PATH": os.defpath,
            "LANG": "C",
            "LC_ALL": "C",
            "HOME": str(path.parent),
            "TMPDIR": str(path.parent),
            "XDG_CACHE_HOME": str(path.parent),
        }
        # A fixed server-owned filename and explicit image2 demuxer cannot refer to
        # playlists, patterns or network protocols hidden inside an uploaded file.
        input_arguments = [
            "-max_alloc",
            str(MAX_DECODER_ALLOCATION),
            "-protocol_whitelist",
            "file",
            "-f",
            "image2",
            "-pattern_type",
            "none",
            "-i",
            path.name,
        ]
        try:
            async with asyncio.timeout(IMAGE_VALIDATION_SECONDS):
                result = await self.runner.run(
                    [
                        str(self.ffprobe),
                        "-v",
                        "error",
                        *input_arguments,
                        "-show_entries",
                        "stream=codec_name,codec_type,width,height",
                        "-of",
                        "json",
                    ],
                    cwd=path.parent,
                    environment=environment,
                    timeout=IMAGE_VALIDATION_SECONDS,
                )
                if result.returncode or result.stderr:
                    raise ValueError
                metadata = json.loads(result.stdout)
                streams = metadata.get("streams")
                if not isinstance(streams, list) or len(streams) != 1:
                    raise ValueError
                stream = streams[0]
                if (
                    not isinstance(stream, dict)
                    or stream.get("codec_type") != "video"
                    or stream.get("codec_name") != EXPECTED_CODECS[mime_type]
                ):
                    raise ValueError
                width, height = stream.get("width"), stream.get("height")
                validate_dimensions(width, height)
                result = await self.runner.run(
                    [
                        str(self.ffmpeg),
                        "-nostdin",
                        "-v",
                        "error",
                        "-xerror",
                        "-err_detect",
                        "explode",
                        "-threads",
                        "1",
                        *input_arguments,
                        "-map",
                        "0:v:0",
                        "-frames:v",
                        "1",
                        "-an",
                        "-sn",
                        "-dn",
                        "-f",
                        "null",
                        "-",
                    ],
                    cwd=path.parent,
                    environment=environment,
                    timeout=IMAGE_VALIDATION_SECONDS,
                )
                if result.returncode or result.stderr:
                    raise ValueError
                return width, height
        except (OSError, TimeoutError, PreparationError) as exc:
            raise VisualAssetError(
                "Image validation could not run. Check the configured FFmpeg tools and retry.",
                503,
            ) from exc
        except (ValueError, TypeError, AttributeError, RecursionError, UnicodeError) as exc:
            raise VisualAssetError(
                "This image could not be decoded. Upload another static image."
            ) from exc
