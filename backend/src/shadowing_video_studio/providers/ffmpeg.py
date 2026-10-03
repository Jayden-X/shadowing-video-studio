"""FFmpeg fixed-template adapter. User text/path values never enter a filter expression."""

import asyncio
import hashlib
import json
import math
import os
import re
import struct
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

from shadowing_video_studio.providers.process import ProcessResult, SubprocessRunner
from shadowing_video_studio.text_processing import PreparationError
from shadowing_video_studio.video_rendering import (
    FRAME_RATE,
    MAX_VIDEO_ASSET_BYTES,
    MAX_VIDEO_JOB_BYTES,
    FrozenVideoSentence,
    FrozenVisualAsset,
    RenderedVideo,
    TextLayout,
    VideoPage,
    VideoProgress,
    VideoRenderingError,
    fit_text,
    video_timeline,
)

MAX_FONT_BYTES = 16 * 1024 * 1024
MAX_AUDIO_BYTES = 64 * 1024 * 1024
# FFmpeg -fs is checked between packets and may exceed its requested size.
# Reserve room for a fixed-template frame/packet and muxer footer; this is not an OS quota.
OUTPUT_MARGIN_BYTES = 4 * 1024 * 1024
PAGE_HEADER_BYTES = 256 * 1024
PCM_BYTES_PER_SECOND = 48000 * 2
MAX_VISUAL_BYTES = 10 * 1024 * 1024
VISUAL_CODECS = {"png": "png", "jpg": "mjpeg", "webp": "webp"}
VISUAL_EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}


def budget_error() -> VideoRenderingError:
    return VideoRenderingError(
        "This video reached its storage budget. Export fewer or shorter sentences.",
        "storage_budget",
    )


class MediaProcessRunner(Protocol):
    async def run(
        self,
        arguments: Sequence[str],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        timeout: float,
    ) -> ProcessResult: ...


class FontMetrics:
    """Small read-only SFNT metrics reader: Unicode cmap + horizontal advances.

    No font fallback: a missing glyph produces an actionable error. Global ink bounds
    provide conservative margins and line heights; drawtext shaping is disabled.
    """

    def __init__(self, data: bytes) -> None:
        try:
            if len(data) > MAX_FONT_BYTES or data[:4] not in (
                b"\x00\x01\x00\x00",
                b"true",
                b"OTTO",
            ):
                raise ValueError
            count = self._u16(data, 4)
            tables = {}
            for index in range(count):
                position = 12 + index * 16
                tag, _, offset, length = struct.unpack_from(">4sIII", data, position)
                if offset + length > len(data):
                    raise ValueError
                tables[tag] = data[offset : offset + length]
            head, hhea, hmtx, cmap = (tables[key] for key in (b"head", b"hhea", b"hmtx", b"cmap"))
            self.units = self._u16(head, 18)
            xmin, ymin, xmax, ymax = struct.unpack_from(">hhhh", head, 36)
            self.ink_margin = max(0, -xmin) + max(0, xmax)
            self.ink_height = ymax - ymin
            self.advances = [self._u16(hmtx, index * 4) for index in range(self._u16(hhea, 34))]
            if not self.units or not self.advances or self.ink_height <= 0:
                raise ValueError
            candidates = []
            for index in range(self._u16(cmap, 2)):
                platform, encoding, offset = struct.unpack_from(">HHI", cmap, 4 + index * 8)
                if platform == 0 or (platform == 3 and encoding in (1, 10)):
                    form = self._u16(cmap, offset)
                    if form in (4, 12):
                        length = (
                            self._u16(cmap, offset + 2)
                            if form == 4
                            else struct.unpack_from(">I", cmap, offset + 4)[0]
                        )
                        if length < 16 or offset + length > len(cmap):
                            raise ValueError
                        candidates.append((form, cmap[offset : offset + length]))
            if not candidates:
                raise ValueError
            self.cmap_format, self.cmap = max(candidates, key=lambda item: item[0])
        except (ValueError, KeyError, struct.error, IndexError) as exc:
            raise VideoRenderingError(
                "Configure a readable TrueType/OpenType font with Unicode glyphs.", "invalid_font"
            ) from exc

    @staticmethod
    def _u16(data: bytes, position: int) -> int:
        return struct.unpack_from(">H", data, position)[0]

    def glyph(self, code: int) -> int:
        try:
            data = self.cmap
            if self.cmap_format == 12:
                count = struct.unpack_from(">I", data, 12)[0]
                for index in range(count):
                    start, end, glyph = struct.unpack_from(">III", data, 16 + index * 12)
                    if start <= code <= end:
                        return glyph + code - start
                return 0
            if code > 0xFFFF:
                return 0
            count = self._u16(data, 6) // 2
            for index in range(count):
                end = self._u16(data, 14 + index * 2)
                start = self._u16(data, 16 + count * 2 + index * 2)
                if start <= code <= end:
                    delta = self._u16(data, 16 + count * 4 + index * 2)
                    range_position = 16 + count * 6 + index * 2
                    offset = self._u16(data, range_position)
                    if not offset:
                        return (code + delta) & 0xFFFF
                    glyph = self._u16(data, range_position + offset + (code - start) * 2)
                    return (glyph + delta) & 0xFFFF if glyph else 0
            return 0
        except (struct.error, IndexError) as exc:
            raise VideoRenderingError(
                "The configured font has invalid glyph metrics.", "invalid_font"
            ) from exc

    def width(self, text: str, font_size: int) -> float:
        advance = 0
        for char in text:
            glyph = self.glyph(ord(char))
            if not glyph:
                raise VideoRenderingError(
                    "The configured font cannot display a character. "
                    "Edit the sentence or configure a font containing it.",
                    "missing_glyph",
                )
            advance += self.advances[min(glyph, len(self.advances) - 1)]
        return (advance + self.ink_margin) * font_size / self.units

    def line_height(self, font_size: int) -> float:
        return math.ceil(self.ink_height * font_size / self.units) + 16


def page_arguments(
    executable: Path,
    page: VideoPage,
    layout: TextLayout,
    index: int,
    file_size_limit: int = MAX_VIDEO_JOB_BYTES - MAX_VIDEO_ASSET_BYTES - OUTPUT_MARGIN_BYTES,
    supports_text_shaping: bool = True,
    background_filename: str | None = None,
    illustration_filename: str | None = None,
) -> list[str]:
    duration = f"{page.duration_seconds:.9f}"
    stem = f"page-{index:04d}"
    # FFmpeg exposes this option only in builds with libfribidi. Without it,
    # shaping is absent already; adding the unsupported option would fail rendering.
    shaping_option = ":text_shaping=0" if supports_text_shaping else ""
    audio_graph = (
        f"[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=mono,"
        f"apad=pad_dur=5,apad=whole_dur={duration},atrim=duration={duration},"
        "asetpts=PTS-STARTPTS,asplit=2[voice][waveinput];"
    )
    image_arguments: list[str] = []
    # Decode a single raster, then repeat the scaled frame a finite number of times.
    # Looping image2 sources can keep feeding the audio/video scheduler after output ends.
    for filename in (background_filename, illustration_filename):
        if filename is None:
            continue
        if not re.fullmatch(r"visual-[0-9]{4}\.(png|jpg|webp)", filename):
            raise VideoRenderingError("Use validated local image assets.", "invalid_visual")
        image_arguments.extend(
            [
                "-protocol_whitelist",
                "file",
                "-f",
                "image2",
                "-pattern_type",
                "none",
                "-framerate",
                str(FRAME_RATE),
                "-threads",
                "1",
                "-c:v",
                VISUAL_CODECS[filename.rsplit(".", 1)[1]],
                "-i",
                filename,
            ]
        )
    background_graph = (
        "[1:v]scale=w=1920:h=1080:force_original_aspect_ratio=increase:out_range=tv,"
        "crop=w=1920:h=1080,setsar=1,format=rgb24,"
        "drawbox=x=0:y=0:w=iw:h=ih:color=black@0.60:t=fill,"
        "format=yuv420p,"
        f"loop=loop={page.frame_count - 1}:size=1:start=0,setpts=N/(30*TB)[background];"
        if background_filename is not None
        else f"color=c=0x101b2d:s=1920x1080:r=30:d={duration}[background];"
    )
    panel_graph = (
        "[background]drawbox=x=1240:y=92:w=584:h=736:color=0x20334c:t=fill,"
        "drawbox=x=96:y=852:w=1728:h=184:color=0x182a40:t=fill"
    )
    if illustration_filename is not None:
        illustration_index = 2 if background_filename is not None else 1
        panel_graph += (
            "[panel];"
            f"[{illustration_index}:v]scale=w=584:h=736:force_original_aspect_ratio=decrease,"
            "setsar=1,format=rgba,"
            f"loop=loop={page.frame_count - 1}:size=1:start=0,setpts=N/(30*TB)[illustration];"
            "[panel][illustration]overlay=x=1240+(584-overlay_w)/2:"
            "y=92+(736-overlay_h)/2:eof_action=repeat:shortest=0[illustrated];"
            "[illustrated]"
        )
    else:
        panel_graph += ","
    graph = (
        audio_graph
        + background_graph
        + panel_graph
        + f"drawtext=fontfile=font.ttf:textfile={stem}.txt:expansion=none:"
        f"fontsize={layout.font_size}:fontcolor=white:x=96:y=96:"
        f"line_spacing=16{shaping_option}[base];"
        "[waveinput]showwaves=s=1728x144:mode=line:rate=30:colors=0x4fbcff:"
        "scale=sqrt:draw=full,fps=30[wave];"
        "[base][wave]overlay=x=96:y=876:eof_action=pass:repeatlast=0,"
        "format=yuv420p[video]"
    )
    return [
        str(executable),
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-n",
        "-protocol_whitelist",
        "file",
        "-f",
        "wav",
        "-i",
        f"audio-{index:04d}.wav",
        *image_arguments,
        "-filter_complex_threads",
        "1",
        "-filter_complex",
        graph,
        "-map",
        "[video]",
        "-map",
        "[voice]",
        "-frames:v",
        str(page.frame_count),
        "-t",
        duration,
        "-r",
        str(FRAME_RATE),
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "21",
        "-threads",
        "2",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "pcm_s16le",
        "-ar",
        "48000",
        "-ac",
        "1",
        "-map_metadata",
        "-1",
        "-fs",
        str(file_size_limit),
        f"{stem}.mkv",
    ]


def concat_arguments(
    executable: Path, file_size_limit: int = MAX_VIDEO_ASSET_BYTES - OUTPUT_MARGIN_BYTES
) -> list[str]:
    return [
        str(executable),
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-n",
        "-protocol_whitelist",
        "file",
        "-f",
        "concat",
        "-safe",
        "1",
        "-i",
        "pages.txt",
        "-map",
        "0:v:0",
        "-map",
        "0:a:0",
        "-c:v",
        "copy",
        "-bsf:v",
        f"setts=pts=round(PTS*TB*{FRAME_RATE}):dts=round(DTS*TB*{FRAME_RATE}):"
        f"duration=1:time_base=1/{FRAME_RATE}",
        "-video_track_timescale",
        str(FRAME_RATE * 1000),
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-ar",
        "48000",
        "-ac",
        "1",
        "-movflags",
        "+faststart",
        "-map_metadata",
        "-1",
        "-fs",
        str(file_size_limit),
        "video.mp4",
    ]


def validate_video_metadata(payload: dict, expected_seconds: float) -> float:
    try:
        video = [item for item in payload["streams"] if item["codec_type"] == "video"]
        audio = [item for item in payload["streams"] if item["codec_type"] == "audio"]
        duration = float(payload["format"]["duration"])
        frame_rate = video[0]["avg_frame_rate"].split("/")
        nominal_rate = video[0]["r_frame_rate"].split("/")
        expected_frames = round(expected_seconds * FRAME_RATE)
        video_seconds = float(video[0]["duration"])
        if (
            len(video) != 1
            or len(audio) != 1
            or video[0]["codec_name"] != "h264"
            or video[0]["width"] != 1920
            or video[0]["height"] != 1080
            or video[0]["pix_fmt"] != "yuv420p"
            or audio[0]["codec_name"] != "aac"
            or audio[0]["sample_rate"] != "48000"
            or audio[0]["channels"] != 1
            or float(frame_rate[0]) / float(frame_rate[1]) != FRAME_RATE
            or float(nominal_rate[0]) / float(nominal_rate[1]) != FRAME_RATE
            or int(video[0]["nb_frames"]) != expected_frames
            or not math.isfinite(video_seconds)
            or abs(video_seconds - expected_frames / FRAME_RATE) > 0.001
            or not math.isfinite(duration)
            or abs(duration - expected_seconds) > 0.25
        ):
            raise ValueError
        return duration
    except (KeyError, IndexError, TypeError, ValueError, ZeroDivisionError, AttributeError) as exc:
        raise VideoRenderingError(
            "The rendered video failed its format or duration check. Retry the export.",
            "invalid_output",
        ) from exc


def _regular_path(path: Path, *, directory: bool = False) -> Path:
    if not path.is_absolute() or any(
        item.is_symlink() or getattr(item, "is_junction", lambda: False)()
        for item in (path, *path.parents)
    ):
        raise VideoRenderingError(
            "Use an application-owned local asset and fresh output folder.", "unsafe_path"
        )
    if not (path.is_dir() if directory else path.is_file()):
        raise VideoRenderingError(
            "A required local asset or output folder is unavailable.", "missing_asset"
        )
    return path.resolve()


def _copy_new(source: Path, destination: Path, expected_bytes: int) -> None:
    with source.open("rb") as incoming, destination.open("xb") as outgoing:
        remaining = expected_bytes
        while remaining:
            chunk = incoming.read(min(remaining, 1024 * 1024))
            if not chunk:
                raise VideoRenderingError(
                    "A frozen input changed. Generate its speech again.", "invalid_audio"
                )
            outgoing.write(chunk)
            remaining -= len(chunk)
        if incoming.read(1):
            raise VideoRenderingError(
                "A frozen input changed. Generate its speech again.", "invalid_audio"
            )


def _visual_content(asset: FrozenVisualAsset) -> bytes:
    if (
        not re.fullmatch(r"[0-9a-f]{32}", asset.id)
        or asset.mime_type not in VISUAL_EXTENSIONS
        or isinstance(asset.size_bytes, bool)
        or not 0 < asset.size_bytes <= MAX_VISUAL_BYTES
        or not re.fullmatch(r"[0-9a-f]{64}", asset.sha256)
    ):
        raise VideoRenderingError("Use validated local image assets.", "invalid_visual")
    source = _regular_path(asset.path)
    with source.open("rb") as handle:
        content = handle.read(MAX_VISUAL_BYTES + 1)
    if len(content) != asset.size_bytes or hashlib.sha256(content).hexdigest() != asset.sha256:
        raise VideoRenderingError(
            "A selected image changed. Select another image or upload it again.", "invalid_visual"
        )
    return content


def _write_new(content: bytes, path: Path) -> None:
    with path.open("xb") as handle:
        handle.write(content)


def directory_bytes(directory: Path) -> int:
    total = 0
    for parent, directories, files in os.walk(directory, followlinks=False):
        for name in directories:
            _regular_path(Path(parent) / name, directory=True)
        for name in files:
            total += _regular_path(Path(parent) / name).stat().st_size
    return total


class FfmpegVideoRenderer:
    def __init__(
        self,
        ffmpeg_executable: Path,
        ffprobe_executable: Path,
        font_path: Path,
        timeout_seconds: float = 600,
        runner: MediaProcessRunner | None = None,
        output_budget_bytes: int = MAX_VIDEO_JOB_BYTES,
        supports_text_shaping: bool = True,
    ) -> None:
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (float, int))
            or not math.isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 3600
        ):
            raise VideoRenderingError(
                "Configure a render timeout between 0 and 3600 seconds.", "invalid_configuration"
            )
        self.ffmpeg = ffmpeg_executable
        self.ffprobe = ffprobe_executable
        self.font_path = font_path
        self.timeout = timeout_seconds
        self.runner = runner or SubprocessRunner()
        if (
            isinstance(output_budget_bytes, bool)
            or not isinstance(output_budget_bytes, int)
            or not 0 < output_budget_bytes <= MAX_VIDEO_JOB_BYTES
        ):
            raise budget_error()
        self.output_budget_bytes = output_budget_bytes
        self.supports_text_shaping = supports_text_shaping

    async def _execute(self, arguments: Sequence[str], directory: Path) -> bytes:
        environment = {
            "PATH": os.defpath,
            "LANG": "C",
            "LC_ALL": "C",
            "HOME": str(directory),
            "TMPDIR": str(directory),
            "XDG_CACHE_HOME": str(directory),
        }
        result = await self.runner.run(
            arguments, cwd=directory, environment=environment, timeout=self.timeout
        )
        if result.returncode:
            if "-fs" in arguments:
                limited_output = directory / arguments[-1]
                if limited_output.exists() and _regular_path(limited_output).stat().st_size >= int(
                    arguments[arguments.index("-fs") + 1]
                ):
                    raise budget_error()
            raise VideoRenderingError(
                "FFmpeg could not complete the export. Check the configured tools and retry."
            )
        return result.stdout

    async def _probe(self, filename: str, directory: Path) -> dict:
        arguments = [
            str(self.ffprobe),
            "-v",
            "error",
            "-protocol_whitelist",
            "file",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
        ]
        if filename.endswith(".wav"):
            arguments.extend(["-f", "wav"])
        arguments.append(filename)
        try:
            payload = json.loads(await self._execute(arguments, directory))
            if not isinstance(payload, dict):
                raise ValueError
            return payload
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise VideoRenderingError(
                "FFmpeg returned invalid media metadata.", "invalid_output"
            ) from exc

    async def render(
        self,
        sentences: Sequence[FrozenVideoSentence],
        job_directory: Path,
        *,
        background: FrozenVisualAsset | None = None,
        on_progress: VideoProgress | None = None,
    ) -> RenderedVideo:
        try:
            async with asyncio.timeout(self.timeout):
                return await self._render(tuple(sentences), job_directory, on_progress, background)
        except TimeoutError as exc:
            raise VideoRenderingError(
                "Video rendering timed out. Retry with fewer sentences.", "timeout"
            ) from exc
        except (OSError, PreparationError) as exc:
            raise VideoRenderingError(
                "The local video tools or assets are unavailable. Check configuration and retry.",
                "unavailable",
            ) from exc

    async def _render(
        self,
        sentences: tuple[FrozenVideoSentence, ...],
        job_directory: Path,
        on_progress: VideoProgress | None,
        background: FrozenVisualAsset | None,
    ) -> RenderedVideo:
        pages = video_timeline(sentences)
        directory = _regular_path(job_directory, directory=True)
        if any(directory.iterdir()):
            raise VideoRenderingError(
                "Use a new empty output folder; previous exports are preserved.", "output_exists"
            )
        for executable in (self.ffmpeg, self.ffprobe):
            if (
                not executable.is_absolute()
                or not executable.is_file()
                or not os.access(executable, os.X_OK)
            ):
                raise VideoRenderingError(
                    "Configure working local FFmpeg and ffprobe executables.", "unavailable"
                )
        font = _regular_path(self.font_path)
        if font.stat().st_size > MAX_FONT_BYTES:
            raise VideoRenderingError("Configure a supported local font.", "invalid_font")
        metrics = FontMetrics(font.read_bytes())
        layouts = [fit_text(page.sentence.text, metrics) for page in pages]
        sources = [_regular_path(page.sentence.audio_path) for page in pages]
        for source in sources:
            if source.suffix.lower() != ".wav" or not 0 < source.stat().st_size <= MAX_AUDIO_BYTES:
                raise VideoRenderingError("Use valid ready WAV speech assets.", "invalid_audio")
        font_bytes = font.stat().st_size
        source_bytes = [source.stat().st_size for source in sources]
        visuals: dict[str, tuple[FrozenVisualAsset, bytes, str]] = {}
        for asset in (background, *(page.sentence.illustration for page in pages)):
            if asset is None:
                continue
            if asset.id in visuals:
                if visuals[asset.id][0] != asset:
                    raise VideoRenderingError(
                        "Selected image identities do not match. Select the images again.",
                        "invalid_visual",
                    )
                continue
            content = await asyncio.to_thread(_visual_content, asset)
            if sum(len(value[1]) for value in visuals.values()) + len(content) > 64 * 1024 * 1024:
                raise budget_error()
            extension = VISUAL_EXTENSIONS[asset.mime_type]
            filename = f"visual-{len(visuals) + 1:04d}.{extension}"
            visuals[asset.id] = (asset, content, filename)
        # Millisecond MKV header durations can accumulate drift across pages. Frozen
        # frame-grid durations set concat offsets; setts restores each packet's grid
        # while preserving separate PTS/DTS and therefore H264 B-frame ordering.
        manifest = "".join(
            f"file 'page-{index:04d}.mkv'\nduration {page.duration_seconds:.9f}\n"
            for index, page in enumerate(pages, 1)
        )
        baseline = (
            font_bytes
            + sum(source_bytes)
            + sum(len(layout.text.encode("utf-8")) for layout in layouts)
            + len(manifest.encode("utf-8"))
            + sum(len(value[1]) for value in visuals.values())
        )
        minimum_pages = sum(
            math.ceil(page.duration_seconds * PCM_BYTES_PER_SECOND) + PAGE_HEADER_BYTES
            for page in pages
        )
        if (
            baseline + minimum_pages + MAX_VIDEO_ASSET_BYTES + OUTPUT_MARGIN_BYTES
            > self.output_budget_bytes
        ):
            raise budget_error()
        await asyncio.to_thread(_copy_new, font, directory / "font.ttf", font_bytes)
        for _, content, filename in visuals.values():
            await asyncio.to_thread(_write_new, content, directory / filename)
        for index, (page, source, layout) in enumerate(
            zip(pages, sources, layouts, strict=True), 1
        ):
            await asyncio.to_thread(
                _copy_new, source, directory / f"audio-{index:04d}.wav", source_bytes[index - 1]
            )
            with (directory / f"page-{index:04d}.txt").open(
                "x", encoding="utf-8", newline="\n"
            ) as output:
                output.write(layout.text)
            metadata = await self._probe(f"audio-{index:04d}.wav", directory)
            try:
                audio = metadata["streams"]
                duration = float(metadata["format"]["duration"])
                if (
                    len(audio) != 1
                    or audio[0]["codec_type"] != "audio"
                    or not isinstance(audio[0]["codec_name"], str)
                    or not audio[0]["codec_name"].startswith("pcm_")
                    or not math.isfinite(duration)
                    or duration <= 0
                    or abs(duration - page.sentence.duration_seconds) > 0.01
                ):
                    raise ValueError
            except (KeyError, TypeError, ValueError) as exc:
                raise VideoRenderingError(
                    "Speech audio no longer matches the frozen sentence. Generate it again.",
                    "invalid_audio",
                ) from exc
        remaining_frames = sum(page.frame_count for page in pages)
        for index, (page, layout) in enumerate(zip(pages, layouts, strict=True), 1):
            available = (
                self.output_budget_bytes
                - directory_bytes(directory)
                - len(manifest.encode("utf-8"))
                - MAX_VIDEO_ASSET_BYTES
                - OUTPUT_MARGIN_BYTES
            )
            page_limit = available * page.frame_count // remaining_frames
            if (
                page_limit
                <= math.ceil(page.duration_seconds * PCM_BYTES_PER_SECOND) + PAGE_HEADER_BYTES
            ):
                raise budget_error()
            await self._execute(
                page_arguments(
                    self.ffmpeg,
                    page,
                    layout,
                    index,
                    page_limit,
                    supports_text_shaping=self.supports_text_shaping,
                    background_filename=visuals[background.id][2] if background else None,
                    illustration_filename=visuals[page.sentence.illustration.id][2]
                    if page.sentence.illustration
                    else None,
                ),
                directory,
            )
            page_output = _regular_path(directory / f"page-{index:04d}.mkv")
            page_size = page_output.stat().st_size
            if (
                page_size >= page_limit
                or directory_bytes(directory) > self.output_budget_bytes - MAX_VIDEO_ASSET_BYTES
            ):
                raise budget_error()
            if not page_size:
                raise VideoRenderingError("The renderer produced an empty page.", "invalid_output")
            remaining_frames -= page.frame_count
            if on_progress:
                on_progress(index, len(pages))
        with (directory / "pages.txt").open("x", encoding="utf-8", newline="\n") as output:
            output.write(manifest)
        final_limit = min(
            MAX_VIDEO_ASSET_BYTES - OUTPUT_MARGIN_BYTES,
            self.output_budget_bytes - directory_bytes(directory) - OUTPUT_MARGIN_BYTES,
        )
        if final_limit <= 0:
            raise budget_error()
        await self._execute(concat_arguments(self.ffmpeg, final_limit), directory)
        output_path = _regular_path(directory / "video.mp4")
        output_size = output_path.stat().st_size
        if output_size >= final_limit or directory_bytes(directory) > self.output_budget_bytes:
            raise budget_error()
        if not output_size:
            raise VideoRenderingError("The renderer produced an empty video.", "invalid_output")
        expected = sum(page.duration_seconds for page in pages)
        duration = validate_video_metadata(await self._probe("video.mp4", directory), expected)
        return RenderedVideo(output_path, duration)
