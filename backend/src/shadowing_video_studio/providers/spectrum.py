"""Reference-style frequency bars, streamed as transparent PNGs without media files."""

import asyncio
import cmath
import math
import struct
import wave
import zlib
from collections.abc import AsyncIterator, Sequence
from pathlib import Path

from shadowing_video_studio.video_rendering import FRAME_RATE, VideoRenderingError

SAMPLE_RATE = 24000
SAMPLES_PER_FRAME = SAMPLE_RATE // FRAME_RATE
FFT_SIZE = 2048
BAR_COUNT = 36
LAYER_WIDTH, LAYER_HEIGHT = 1260, 180
SILENCE_THRESHOLD = 0.001
BATCH_FRAMES = 8
_WINDOW = tuple(
    0.5 - 0.5 * math.cos(2 * math.pi * n / (SAMPLES_PER_FRAME - 1))
    for n in range(SAMPLES_PER_FRAME)
)
_REVERSED = tuple(int(f"{n:011b}"[::-1], 2) for n in range(FFT_SIZE))
_TWIDDLES = tuple(cmath.exp(-2j * math.pi * n / FFT_SIZE) for n in range(FFT_SIZE // 2))
_EDGES = tuple(80 * 100 ** (n / BAR_COUNT) for n in range(BAR_COUNT + 1))
_BINS = tuple(
    tuple(n for n in range(FFT_SIZE // 2 + 1) if low <= n * SAMPLE_RATE / FFT_SIZE < high)
    for low, high in zip(_EDGES, _EDGES[1:], strict=False)
)


def band_heights(samples: Sequence[float]) -> tuple[int, ...]:
    """Match the reference's 800-sample Hann window, FFT bands and RMS envelope."""
    if len(samples) != SAMPLES_PER_FRAME or any(
        not math.isfinite(value) or abs(value) > 1 for value in samples
    ):
        raise VideoRenderingError("Use valid mono speech audio.", "invalid_audio")
    rms = math.sqrt(sum(value * value for value in samples) / SAMPLES_PER_FRAME)
    if rms <= SILENCE_THRESHOLD:
        return (0,) * BAR_COUNT
    values = [0j] * FFT_SIZE
    for n, (value, window) in enumerate(zip(samples, _WINDOW, strict=True)):
        values[_REVERSED[n]] = complex(value * window)
    size = 2
    while size <= FFT_SIZE:
        half, stride = size // 2, FFT_SIZE // size
        for start in range(0, FFT_SIZE, size):
            for offset in range(half):
                left = values[start + offset]
                right = values[start + offset + half] * _TWIDDLES[offset * stride]
                values[start + offset] = left + right
                values[start + offset + half] = left - right
        size *= 2
    energies = tuple(
        math.sqrt(sum(abs(values[n]) ** 2 for n in bins) / len(bins)) for bins in _BINS
    )
    maximum = max(max(energies), 1e-8)
    amplitude = min(1, rms * 9)
    return tuple(
        max(8, int(145 * amplitude * (0.25 + 0.75 * math.sqrt(energy / maximum))))
        for energy in energies
    )


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def spectrum_png(heights: Sequence[int]) -> bytes:
    """Draw black, vertically centered rounded bars on a fully transparent layer."""
    if len(heights) != BAR_COUNT or any(
        isinstance(height, bool) or not isinstance(height, int) or not 0 <= height <= 145
        for height in heights
    ):
        raise ValueError("Invalid spectrum heights")
    # Only one small RGBA frame exists at a time. PNG filtering uses a zero filter byte.
    row_bytes = LAYER_WIDTH * 4 + 1
    pixels = bytearray(row_bytes * LAYER_HEIGHT)
    for bar, height in enumerate(heights):
        if not height:
            continue
        top, bottom = 90 - height / 2, 90 + height / 2
        radius = min(7, height / 2)
        x = 118 + bar * 29
        # Half-open bounds sampled at pixel centers keep width/height exact.
        for y in range(math.ceil(top - 0.5), math.ceil(bottom - 0.5)):
            dy = max(top + radius - (y + 0.5), y + 0.5 - (bottom - radius), 0)
            inset = radius - math.sqrt(max(0, radius * radius - dy * dy))
            left, right = math.ceil(x + inset - 0.5), math.ceil(x + 16 - inset - 0.5)
            for column in range(left, right):
                pixels[y * row_bytes + 1 + column * 4 + 3] = 255
    header = struct.pack(">IIBBBBB", LAYER_WIDTH, LAYER_HEIGHT, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(pixels, 3))
        + _chunk(b"IEND", b"")
    )


_SILENT_PNG = spectrum_png((0,) * BAR_COUNT)


def _audio_frames(path: Path) -> int:
    try:
        with wave.open(str(path), "rb") as audio:
            if (
                audio.getnchannels() != 1
                or audio.getframerate() != SAMPLE_RATE
                or audio.getsampwidth() != 2
                or audio.getcomptype() != "NONE"
                or not 0 < audio.getnframes() <= 300 * SAMPLE_RATE
            ):
                raise ValueError
            return audio.getnframes()
    except (OSError, wave.Error, EOFError, ValueError) as exc:
        raise VideoRenderingError(
            "Use valid 24 kHz mono PCM speech audio.", "invalid_audio"
        ) from exc


def _frame_batch(path: Path, start: int, count: int, audio_frames: int) -> bytes:
    first_sample = start * SAMPLES_PER_FRAME
    if first_sample >= audio_frames:
        return _SILENT_PNG * count
    try:
        with wave.open(str(path), "rb") as audio:
            audio.setpos(first_sample)
            sample_count = min(count * SAMPLES_PER_FRAME, audio_frames - first_sample)
            content = audio.readframes(sample_count)
            if len(content) != sample_count * 2:
                raise ValueError
        samples = tuple(value[0] / 32768 for value in struct.iter_unpack("<h", content))
        frames = []
        for offset in range(count):
            frame = samples[offset * SAMPLES_PER_FRAME : (offset + 1) * SAMPLES_PER_FRAME]
            if not frame:
                frames.append(_SILENT_PNG)
                continue
            padded = (*frame, *((0.0,) * (SAMPLES_PER_FRAME - len(frame))))
            frames.append(spectrum_png(band_heights(padded)))
        return b"".join(frames)
    except (OSError, wave.Error, EOFError, ValueError) as exc:
        raise VideoRenderingError(
            "The frozen speech audio could not be read.", "invalid_audio"
        ) from exc


async def waveform_frames(path: Path, frame_count: int) -> AsyncIterator[bytes]:
    """Finite, backpressured batches; analysis and compression stay off the event loop."""
    audio_frames = await asyncio.to_thread(_audio_frames, path)
    for start in range(0, frame_count, BATCH_FRAMES):
        yield await asyncio.to_thread(
            _frame_batch, path, start, min(BATCH_FRAMES, frame_count - start), audio_frames
        )
