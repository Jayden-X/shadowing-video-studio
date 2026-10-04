import asyncio
import math
import struct
import wave
import zlib

import pytest

from shadowing_video_studio.providers.spectrum import (
    BAR_COUNT,
    LAYER_HEIGHT,
    LAYER_WIDTH,
    band_heights,
    spectrum_png,
    waveform_frames,
)
from shadowing_video_studio.video_rendering import VideoRenderingError


def tone(frequency: float, amplitude: float = 0.2) -> tuple[float, ...]:
    return tuple(
        amplitude * math.sin(2 * math.pi * frequency * index / 24000) for index in range(800)
    )


def decode_rgba_png(content: bytes) -> tuple[int, int, bytes]:
    assert content.startswith(b"\x89PNG\r\n\x1a\n")
    offset = 8
    image_data = bytearray()
    width = height = 0
    while offset < len(content):
        size = struct.unpack_from(">I", content, offset)[0]
        kind = content[offset + 4 : offset + 8]
        payload = content[offset + 8 : offset + 8 + size]
        checksum = struct.unpack_from(">I", content, offset + 8 + size)[0]
        assert checksum == zlib.crc32(kind + payload)
        if kind == b"IHDR":
            width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", payload
            )
            assert (bit_depth, color_type, compression, filtering, interlace) == (8, 6, 0, 0, 0)
        elif kind == b"IDAT":
            image_data.extend(payload)
        offset += size + 12
        if kind == b"IEND":
            break
    rows = zlib.decompress(image_data)
    assert len(rows) == height * (width * 4 + 1)
    assert all(rows[row * (width * 4 + 1)] == 0 for row in range(height))
    return width, height, bytes(rows)


def split_pngs(content: bytes) -> tuple[bytes, ...]:
    images = []
    offset = 0
    while offset < len(content):
        assert content[offset : offset + 8] == b"\x89PNG\r\n\x1a\n"
        start = offset
        cursor = offset + 8
        while True:
            size = struct.unpack_from(">I", content, cursor)[0]
            kind = content[cursor + 4 : cursor + 8]
            cursor += size + 12
            if kind == b"IEND":
                break
        offset = cursor
        images.append(content[start:offset])
    assert offset == len(content)
    return tuple(images)


def write_wave(path, samples: tuple[int, ...], *, rate: int = 24000, channels: int = 1) -> None:
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(channels)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def test_band_heights_hide_silence_and_follow_frequency():
    assert band_heights((0.0,) * 800) == (0,) * BAR_COUNT
    assert band_heights(tone(200, 0.0005)) == (0,) * BAR_COUNT

    low = band_heights(tone(200))
    high = band_heights(tone(6000))
    assert len(low) == len(high) == BAR_COUNT
    assert low.index(max(low)) < 12
    assert high.index(max(high)) > 24


def test_spectrum_png_has_black_rounded_bars_and_transparent_background():
    image = spectrum_png((40,) + (0,) * (BAR_COUNT - 1))
    width, height, rows = decode_rgba_png(image)
    assert (width, height) == (LAYER_WIDTH, LAYER_HEIGHT)

    def pixel(x: int, y: int) -> tuple[int, int, int, int]:
        start = y * (width * 4 + 1) + 1 + x * 4
        return tuple(rows[start : start + 4])

    assert [x for x in range(width) if pixel(x, 90)[3]] == list(range(118, 134))
    assert pixel(118, 90) == (0, 0, 0, 255)
    assert pixel(118, 70)[3] == 0  # Rounded upper corner.
    assert pixel(125, 70) == (0, 0, 0, 255)
    assert all(pixel(x, 110)[3] == 0 for x in range(118, 134))  # Exact 40px bar height.
    assert pixel(117, 90)[3] == 0
    assert pixel(500, 90)[3] == 0  # No backing panel.


def test_waveform_frames_streams_only_the_requested_frames_in_bounded_batches(tmp_path):
    path = tmp_path / "speech.wav"
    active = tuple(round(value * 32767) for value in tone(500))
    write_wave(path, active)

    async def scenario():
        return [batch async for batch in waveform_frames(path, 17)]

    batches = asyncio.run(scenario())
    frames = tuple(frame for batch in batches for frame in split_pngs(batch))
    assert [len(split_pngs(batch)) for batch in batches] == [8, 8, 1]
    assert len(frames) == 17
    first_width, first_height, first_pixels = decode_rgba_png(frames[0])
    first_stride = first_width * 4 + 1
    assert any(
        first_pixels[row * first_stride + 1 + column * 4 + 3]
        for row in range(first_height)
        for column in range(first_width)
    )
    for frame in frames[1:]:
        frame_width, frame_height, pixels = decode_rgba_png(frame)
        stride = frame_width * 4 + 1
        assert not any(
            pixels[row * stride + 1 + column * 4 + 3]
            for row in range(frame_height)
            for column in range(frame_width)
        )


def test_waveform_frames_rejects_corrupt_or_unsupported_audio(tmp_path):
    corrupt = tmp_path / "corrupt.wav"
    corrupt.write_bytes(b"not a wave file")
    unsupported = tmp_path / "stereo.wav"
    write_wave(unsupported, (0,) * 800, channels=2)

    async def assert_invalid(path):
        with pytest.raises(VideoRenderingError) as error:
            await anext(waveform_frames(path, 1))
        assert error.value.code == "invalid_audio"

    asyncio.run(assert_invalid(corrupt))
    asyncio.run(assert_invalid(unsupported))
