from types import SimpleNamespace

import pytest

from askthe.adapters.files import TranscriptFileSource
from askthe.adapters.youtube import FetchError, meta_from_info, transcript_from_fetched
from askthe.core.captions import caption_file_text, clean_caption_text
from askthe.core.models import TranscriptKind

VTT = """WEBVTT
Kind: captions

NOTE a comment block

00:00:00.000 --> 00:00:02.000
<c>Riddle me this,</c> why is this

00:00:02.000 --> 00:00:04.000 align:start
Riddle me this, why is this

00:00:04.000 --> 00:00:06.500
yellow symbol on every boot?
"""

SRT = """1
00:00:00,000 --> 00:00:02,000
Hello everyone.

2
00:00:02,000 --> 00:00:04,000
It's Michael.
"""


def test_caption_files_become_plain_text_without_timing_or_repeats():
    assert caption_file_text(VTT) == "Riddle me this, why is this yellow symbol on every boot?"
    assert caption_file_text(SRT) == "Hello everyone. It's Michael."


def test_cleaning_removes_noise_but_keeps_the_words():
    raw = ">> Suddenly, the climbers [music] were flying >> up mountains [Applause]"
    assert clean_caption_text(raw) == "Suddenly, the climbers were flying up mountains"
    assert clean_caption_text("a -> b >>c") == "a -> b >>c"  # only standalone markers


@pytest.mark.parametrize(
    ("filename", "content"),
    [("abc.vtt", VTT), ("abc.srt", SRT), ("abc.txt", "  Pasted   transcript\ntext. ")],
)
def test_transcript_files_are_read_by_extension(tmp_path, filename, content):
    (tmp_path / filename).write_text(content)
    source = TranscriptFileSource(tmp_path, kind=TranscriptKind.MANUAL)
    transcript = source.get_transcript("abc")
    assert transcript.kind == "manual"
    assert transcript.text and "  " not in transcript.text


def test_missing_transcript_file_is_a_lookup_error(tmp_path):
    with pytest.raises(LookupError):
        TranscriptFileSource(tmp_path, kind=TranscriptKind.AUTO).get_transcript("nope")


def test_ytdlp_info_maps_to_video_meta():
    meta = meta_from_info(
        {
            "id": "VtBFkFZoaII",
            "title": "Why The Same Brand Is On The Bottom Of Every Boot",
            "description": "Links: ...",
            "upload_date": "20260412",
            "duration": 1234,
            "chapters": [{"title": "Intro", "start_time": 0}, {"title": "Grip", "start_time": 90}],
            "tags": ["boots"],
            "view_count": 1000,
        }
    )
    assert meta.published_at.year == 2026 and meta.published_at.month == 4
    assert meta.chapters == ["Intro", "Grip"]
    assert meta.duration_s == 1234


def test_ytdlp_info_without_a_date_is_an_error():
    with pytest.raises(FetchError):
        meta_from_info({"id": "x", "title": "t"})


def test_transcript_api_result_maps_to_plain_text():
    snippet = SimpleNamespace
    fetched = SimpleNamespace(
        is_generated=True,
        language_code="en",
        snippets=[
            snippet(text="hello\nthere", start=0, duration=1),
            snippet(text="world", start=1, duration=1),
        ],
    )
    transcript = transcript_from_fetched(fetched)
    assert transcript.kind == "auto"
    assert transcript.text == "hello there world"
