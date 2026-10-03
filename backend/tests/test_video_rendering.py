from pathlib import Path

import pytest

from shadowing_video_studio.video_rendering import (
    FRAME_RATE,
    FrozenVideoSentence,
    VideoRenderingError,
    fit_text,
    video_timeline,
)


class FixedMetrics:
    def width(self, text, font_size):
        return len(text) * font_size

    def line_height(self, font_size):
        return font_size + 16


def sentence(identifier="one", text="Hello.", duration=1.08):
    return FrozenVideoSentence(identifier, text, Path("/synthetic/speech.wav"), duration)


def test_timeline_has_five_second_pause_after_every_sentence_including_final():
    pages = video_timeline([sentence(), sentence("two", duration=2)])
    assert pages[0].start_seconds == 0
    assert pages[1].start_seconds == pages[0].duration_seconds
    for page in pages:
        silence = page.duration_seconds - page.sentence.duration_seconds
        assert 5 <= silence < 5 + 1 / FRAME_RATE
        assert page.duration_seconds == page.frame_count / FRAME_RATE


@pytest.mark.parametrize("duration", [0, -1, True, float("nan"), float("inf"), 301, "1"])
def test_timeline_rejects_invalid_audio_duration(duration):
    with pytest.raises(VideoRenderingError, match="valid, unique"):
        video_timeline([sentence(duration=duration)])


@pytest.mark.parametrize("sentences", [[], [sentence(), sentence()], [sentence("")]])
def test_timeline_rejects_missing_or_duplicate_id(sentences):
    with pytest.raises(VideoRenderingError):
        video_timeline(sentences)


def test_layout_wraps_quotes_unicode_percent_and_filter_punctuation_as_data():
    text = "It's “safe”: 100% %{localtime}; [nothing] $(runs)\\path."
    layout = fit_text(text, FixedMetrics())
    assert " ".join(layout.text.split()) == text
    assert all(
        FixedMetrics().width(line, layout.font_size) <= 1000 for line in layout.text.splitlines()
    )


def test_layout_wraps_long_token_without_losing_characters():
    text = "a" * 50
    layout = fit_text(text, FixedMetrics())
    assert layout.text.replace("\n", "") == text


def test_layout_reduces_font_before_rejecting_text():
    layout = fit_text("a " * 80, FixedMetrics())
    assert layout.font_size < 64
    assert len(layout.text.splitlines()) * FixedMetrics().line_height(layout.font_size) <= 720


@pytest.mark.parametrize("text", ["", " ", "a\x00b", "\ud800", "a\u202eb"])
def test_layout_rejects_control_or_invalid_text(text):
    with pytest.raises(VideoRenderingError) as error:
        fit_text(text, FixedMetrics())
    assert error.value.code == "invalid_text"


def test_layout_requests_split_instead_of_truncating():
    with pytest.raises(VideoRenderingError, match="Split") as error:
        fit_text("W" * 4000, FixedMetrics())
    assert error.value.code == "text_too_long"
