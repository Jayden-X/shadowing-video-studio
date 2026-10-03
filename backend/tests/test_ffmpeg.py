import asyncio
import json
import os
import struct
from pathlib import Path

import pytest

from shadowing_video_studio.providers.ffmpeg import (
    FfmpegVideoRenderer,
    FontMetrics,
    concat_arguments,
    page_arguments,
    validate_video_metadata,
)
from shadowing_video_studio.providers.process import ProcessResult
from shadowing_video_studio.text_processing import PreparationError
from shadowing_video_studio.video_rendering import (
    FrozenVideoSentence,
    TextLayout,
    VideoRenderingError,
    video_timeline,
)


def font_bytes():
    # Tiny synthetic SFNT metrics, not a redistributable/generated media asset.
    head = bytearray(54)
    struct.pack_into(">H", head, 18, 1000)
    struct.pack_into(">hhhh", head, 36, 0, -200, 1000, 800)
    hhea = bytearray(36)
    struct.pack_into(">H", hhea, 34, 100)
    segments = [
        (32, 126, -31),
        (233, 233, 2 - 233),
        (0x2018, 0x201D, 3 - 0x2018),
        (0xFFFF, 0xFFFF, 1),
    ]
    count = len(segments)
    subtable = struct.pack(">HHHHHHH", 4, 16 + count * 8, 0, count * 2, 0, 0, 0)
    subtable += b"".join(struct.pack(">H", end) for _, end, _ in segments) + b"\0\0"
    subtable += b"".join(struct.pack(">H", start) for start, _, _ in segments)
    subtable += b"".join(struct.pack(">H", delta & 0xFFFF) for _, _, delta in segments)
    subtable += b"\0\0" * count
    cmap = struct.pack(">HHHHI", 0, 1, 3, 1, 12) + subtable
    tables = {
        b"head": bytes(head),
        b"hhea": bytes(hhea),
        b"hmtx": struct.pack(">HH", 500, 0) * 100,
        b"cmap": cmap,
    }
    offset = 12 + len(tables) * 16
    records = bytearray()
    contents = bytearray()
    for tag, data in tables.items():
        records += struct.pack(">4sIII", tag, 0, offset, len(data))
        contents += data
        offset += len(data)
    return struct.pack(">IHHHH", 0x00010000, len(tables), 0, 0, 0) + records + contents


def video_metadata(duration=6):
    return {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "avg_frame_rate": "30/1",
                "pix_fmt": "yuv420p",
            },
            {"codec_type": "audio", "codec_name": "aac", "sample_rate": "48000", "channels": 1},
        ],
        "format": {"duration": str(duration)},
    }


class FakeRunner:
    def __init__(self, *, duration=1, output_seconds=6, failure=None, metadata=None, cap_hit=False):
        self.calls = []
        self.duration = duration
        self.output_seconds = output_seconds
        self.failure = failure
        self.metadata = metadata
        self.cap_hit = cap_hit

    async def run(self, arguments, **options):
        self.calls.append((list(arguments), options))
        cwd = options["cwd"]
        if arguments[-1].endswith(".wav"):
            return ProcessResult(
                0,
                json.dumps(
                    {
                        "streams": [{"codec_type": "audio", "codec_name": "pcm_s16le"}],
                        "format": {"duration": str(self.duration)},
                    }
                ).encode(),
            )
        if arguments[-1] == "video.mp4" and "-show_streams" in arguments:
            return ProcessResult(
                0, json.dumps(self.metadata or video_metadata(self.output_seconds)).encode()
            )
        if self.failure == "timeout":
            raise TimeoutError("private source/path")
        if self.failure == "overflow":
            raise PreparationError("private raw output")
        if self.failure:
            return ProcessResult(1, b"", b"private source/path")
        if self.cap_hit:
            with (cwd / arguments[-1]).open("xb") as output:
                output.truncate(int(arguments[arguments.index("-fs") + 1]))
        else:
            (cwd / arguments[-1]).write_bytes(b"synthetic fixture")
        return ProcessResult(0, b"")


def setup_renderer(tmp_path, runner=None):
    tool = tmp_path / "configured-ffmpeg"
    tool.write_text("synthetic fake executable")
    tool.chmod(0o755)
    separator = ":" if os.name != "nt" else "_"
    font = tmp_path / f"font 'quoted'{separator} [é].ttf"
    font.write_bytes(font_bytes())
    audio = tmp_path / f"source 'quoted'{separator} [é].wav"
    audio.write_bytes(b"synthetic immutable audio")
    job = tmp_path / f"fresh 'quoted'{separator} [é] output"
    job.mkdir()
    renderer = FfmpegVideoRenderer(tool, tool, font, runner=runner or FakeRunner())
    sentence = FrozenVideoSentence("one", "It's “safe”: %{localtime}; [é].", audio, 1)
    return renderer, sentence, job


def test_metrics_read_unicode_advances_and_reject_missing_glyph():
    metrics = FontMetrics(font_bytes())
    assert metrics.width("Aé’", 64) == 160
    assert metrics.line_height(64) == 80
    with pytest.raises(VideoRenderingError) as error:
        metrics.width("🦄", 64)
    assert error.value.code == "missing_glyph"


@pytest.mark.parametrize("data", [b"", b"ttcf" + b"\0" * 100, font_bytes()[:80]])
def test_invalid_font_returns_safe_error(data):
    with pytest.raises(VideoRenderingError) as error:
        FontMetrics(data)
    assert error.value.code == "invalid_font"


def test_commands_use_fixed_relative_files_and_no_source_interpolation():
    sentence = FrozenVideoSentence(
        "private-id", "private %{localtime}'", Path("/private/path.wav"), 1
    )
    arguments = page_arguments(
        Path("/configured/ffmpeg"), video_timeline([sentence])[0], TextLayout(sentence.text, 64), 1
    )
    graph = arguments[arguments.index("-filter_complex") + 1]
    assert "private" not in graph
    assert "expansion=none" in graph and "textfile=page-0001.txt" in graph
    assert "fontfile=font.ttf" in graph and "showwaves=" in graph and "apad=pad_dur=5" in graph
    assert "text_shaping=0" in graph
    unshaped = page_arguments(
        Path("/configured/ffmpeg"),
        video_timeline([sentence])[0],
        TextLayout(sentence.text, 64),
        1,
        supports_text_shaping=False,
    )
    unshaped_graph = unshaped[unshaped.index("-filter_complex") + 1]
    assert "text_shaping" not in unshaped_graph and "line_spacing=16[base]" in unshaped_graph
    assert "1920x1080" in graph and "-n" in arguments and "-y" not in arguments
    assert int(arguments[arguments.index("-fs") + 1]) > 0
    assert arguments[arguments.index("-i") + 1] == "audio-0001.wav"
    final = concat_arguments(Path("/configured/ffmpeg"))
    assert final[final.index("-c:a") + 1] == "aac"
    assert final[final.index("-safe") + 1] == "1"
    assert 0 < int(final[final.index("-fs") + 1]) < 128 * 1024 * 1024


def test_storage_budget_prevents_encoding_and_never_publishes_size_limited_page(tmp_path):
    runner = FakeRunner(cap_hit=True)
    renderer, sentence, job = setup_renderer(tmp_path, runner)
    original = sentence.audio_path.read_bytes()
    renderer.output_budget_bytes = 128 * 1024 * 1024
    with pytest.raises(VideoRenderingError) as error:
        asyncio.run(renderer.render([sentence], job))
    assert error.value.code == "storage_budget" and not runner.calls and not list(job.iterdir())
    renderer.output_budget_bytes = 134 * 1024 * 1024
    with pytest.raises(VideoRenderingError) as error:
        asyncio.run(renderer.render([sentence], job))
    assert error.value.code == "storage_budget"
    assert "shorter" in error.value.message
    assert (job / "page-0001.mkv").exists() and not (job / "video.mp4").exists()
    assert all(arguments[-1] != "video.mp4" for arguments, _ in runner.calls)
    assert sentence.audio_path.read_bytes() == original


def test_render_preserves_originals_uses_fresh_directory_and_reports_progress(tmp_path):
    runner = FakeRunner(output_seconds=12)
    renderer, sentence, job = setup_renderer(tmp_path, runner)
    second = FrozenVideoSentence("two", "A second sentence.", sentence.audio_path, 1)
    original = sentence.audio_path.read_bytes()
    progress = []
    result = asyncio.run(
        renderer.render(
            [sentence, second], job, on_progress=lambda done, total: progress.append((done, total))
        )
    )
    assert result.path == job / "video.mp4" and result.duration_seconds == 12
    assert (result.width, result.height, result.frame_rate) == (1920, 1080, 30)
    assert progress == [(1, 2), (2, 2)]
    assert sentence.audio_path.read_bytes() == original
    assert " ".join((job / "page-0001.txt").read_text(encoding="utf-8").split()) == sentence.text
    assert (job / "pages.txt").read_text() == "file 'page-0001.mkv'\nfile 'page-0002.mkv'\n"
    for arguments, options in runner.calls:
        assert options["cwd"] == job and options["timeout"] == 600
        assert "shell" not in options
        assert options["environment"]["TMPDIR"] == str(job)
        assert str(sentence.audio_path) not in arguments
    with pytest.raises(VideoRenderingError) as error:
        asyncio.run(renderer.render([sentence], job))
    assert error.value.code == "output_exists" and result.path.exists()


@pytest.mark.parametrize(
    "failure,code", [("exit", "render_failed"), ("timeout", "timeout"), ("overflow", "unavailable")]
)
def test_failure_is_safe_and_preserves_source_and_job_evidence(tmp_path, failure, code):
    renderer, sentence, job = setup_renderer(tmp_path, FakeRunner(failure=failure))
    with pytest.raises(VideoRenderingError) as error:
        asyncio.run(renderer.render([sentence], job))
    assert error.value.code == code
    assert "private" not in str(error.value)
    assert sentence.audio_path.exists() and (job / "audio-0001.wav").exists()


def test_duration_mismatch_rejected_before_encoding(tmp_path):
    runner = FakeRunner(duration=2)
    renderer, sentence, job = setup_renderer(tmp_path, runner)
    with pytest.raises(VideoRenderingError) as error:
        asyncio.run(renderer.render([sentence], job))
    assert error.value.code == "invalid_audio"
    assert all("-show_streams" in arguments for arguments, _ in runner.calls)


def test_missing_audio_and_text_overflow_do_not_invoke_process(tmp_path):
    renderer, sentence, job = setup_renderer(tmp_path)
    sentence.audio_path.unlink()
    with pytest.raises(VideoRenderingError) as error:
        asyncio.run(renderer.render([sentence], job))
    assert error.value.code == "missing_asset"
    assert not renderer.runner.calls and not list(job.iterdir())
    long = FrozenVideoSentence("one", "W" * 4000, sentence.audio_path, 1)
    with pytest.raises(VideoRenderingError) as error:
        asyncio.run(renderer.render([long], job))
    assert error.value.code == "text_too_long"
    assert not renderer.runner.calls and not list(job.iterdir())


@pytest.mark.skipif(os.name == "nt", reason="Windows accounts may prohibit symlinks")
def test_symlink_job_or_audio_is_rejected_without_writes(tmp_path):
    renderer, sentence, job = setup_renderer(tmp_path)
    link = tmp_path / "job-link"
    link.symlink_to(job, target_is_directory=True)
    with pytest.raises(VideoRenderingError) as error:
        asyncio.run(renderer.render([sentence], link))
    assert error.value.code == "unsafe_path"
    audio_link = tmp_path / "audio-link.wav"
    audio_link.symlink_to(sentence.audio_path)
    linked = FrozenVideoSentence("one", "Hello.", audio_link, 1)
    with pytest.raises(VideoRenderingError) as error:
        asyncio.run(renderer.render([linked], job))
    assert error.value.code == "unsafe_path" and not list(job.iterdir())


@pytest.mark.parametrize("payload", [{}, video_metadata(10), video_metadata(float("nan"))])
def test_output_metadata_rejects_wrong_or_missing_duration(payload):
    with pytest.raises(VideoRenderingError) as error:
        validate_video_metadata(payload, 6)
    assert error.value.code == "invalid_output"


def test_output_metadata_rejects_codec_resolution_and_frame_rate():
    for field, value in (
        ("codec_name", "vp9"),
        ("width", 1280),
        ("avg_frame_rate", "0/0"),
        ("pix_fmt", "yuv444p"),
    ):
        payload = video_metadata()
        payload["streams"][0][field] = value
        with pytest.raises(VideoRenderingError):
            validate_video_metadata(payload, 6)
