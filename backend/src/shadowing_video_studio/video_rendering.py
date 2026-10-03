"""Project-owned video inputs, timeline and fixed-template text layout."""

import math
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

FRAME_RATE = 30
VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
SHADOWING_PAUSE_SECONDS = 5
TEXT_WIDTH = 1000
TEXT_HEIGHT = 720
MAX_VIDEO_SENTENCES = 500
MAX_AUDIO_SECONDS = 300
MAX_VIDEO_ASSET_BYTES = 128 * 1024 * 1024
MAX_VIDEO_JOB_BYTES = 512 * 1024 * 1024


class VideoRenderingError(Exception):
    """Safe application message/code; never raw process output or local paths."""

    def __init__(self, message: str, code: str = "render_failed") -> None:
        super().__init__(message)
        self.message = message
        self.detail = message
        self.code = code


@dataclass(frozen=True)
class FrozenVisualAsset:
    id: str
    path: Path
    size_bytes: int
    sha256: str
    mime_type: str


@dataclass(frozen=True)
class FrozenVideoSentence:
    id: str
    text: str
    audio_path: Path
    duration_seconds: float
    illustration: FrozenVisualAsset | None = None


@dataclass(frozen=True)
class RenderedVideo:
    path: Path
    duration_seconds: float
    width: int = VIDEO_WIDTH
    height: int = VIDEO_HEIGHT
    frame_rate: int = FRAME_RATE


@dataclass(frozen=True)
class VideoPage:
    sentence: FrozenVideoSentence
    start_seconds: float
    duration_seconds: float
    frame_count: int


@dataclass(frozen=True)
class TextLayout:
    text: str
    font_size: int


class TextMetrics(Protocol):
    def width(self, text: str, font_size: int) -> float: ...

    def line_height(self, font_size: int) -> float: ...


VideoProgress = Callable[[int, int], None]


class VideoRenderer(Protocol):
    async def render(
        self,
        sentences: Sequence[FrozenVideoSentence],
        job_directory: Path,
        *,
        background: FrozenVisualAsset | None = None,
        on_progress: VideoProgress | None = None,
    ) -> RenderedVideo: ...


def video_timeline(sentences: Sequence[FrozenVideoSentence]) -> list[VideoPage]:
    if not sentences or len(sentences) > MAX_VIDEO_SENTENCES:
        raise VideoRenderingError("Select between 1 and 500 ready sentences.", "invalid_input")
    pages = []
    ids: set[str] = set()
    total_frames = 0
    for sentence in sentences:
        if (
            not isinstance(sentence.id, str)
            or not sentence.id.strip()
            or len(sentence.id) > 128
            or sentence.id in ids
            or isinstance(sentence.duration_seconds, bool)
            or not isinstance(sentence.duration_seconds, (float, int))
            or not math.isfinite(sentence.duration_seconds)
            or not 0 < sentence.duration_seconds <= MAX_AUDIO_SECONDS
        ):
            raise VideoRenderingError("Select valid, unique ready speech assets.", "invalid_input")
        ids.add(sentence.id)
        # Frame quantization may add less than one frame of silence to a page.
        frames = math.ceil((sentence.duration_seconds + SHADOWING_PAUSE_SECONDS) * FRAME_RATE)
        pages.append(VideoPage(sentence, total_frames / FRAME_RATE, frames / FRAME_RATE, frames))
        total_frames += frames
    return pages


def fit_text(text: str, metrics: TextMetrics) -> TextLayout:
    try:
        valid = (
            isinstance(text, str)
            and bool(text.strip())
            and len(text.encode("utf-16-le")) // 2 <= 4000
            and all(
                unicodedata.category(char) not in {"Cs", "Cf", "Cc"}
                for char in text
                if char not in "\n\r\t"
            )
        )
    except UnicodeError:
        valid = False
    if not valid:
        raise VideoRenderingError(
            "Use readable sentence text without control characters.", "invalid_text"
        )
    paragraphs = [paragraph.split() for paragraph in text.splitlines() if paragraph.strip()]
    for font_size in (64, 56, 48, 42):
        lines: list[str] = []
        for words in paragraphs:
            current = ""
            for word in words:
                candidate = f"{current} {word}" if current else word
                if metrics.width(candidate, font_size) <= TEXT_WIDTH:
                    current = candidate
                    continue
                if current:
                    lines.append(current)
                    current = ""
                # Long tokens are wrapped, never clipped or silently omitted.
                for char in word:
                    candidate = current + char
                    if metrics.width(candidate, font_size) > TEXT_WIDTH:
                        if not current:
                            raise VideoRenderingError(
                                "The configured font cannot fit this text.", "invalid_font"
                            )
                        lines.append(current)
                        current = char
                    else:
                        current = candidate
            if current:
                lines.append(current)
        if lines and len(lines) * metrics.line_height(font_size) <= TEXT_HEIGHT:
            return TextLayout("\n".join(lines), font_size)
    raise VideoRenderingError(
        "This sentence cannot fit the video page. Split it into shorter sentences.", "text_too_long"
    )
