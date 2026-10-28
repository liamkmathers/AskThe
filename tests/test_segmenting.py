import pytest

from askthe.core.segmenting import SegmentingRules, segment_text, video_from_raw
from tests import factories as f

RULES = SegmentingRules(target_words=5, max_words=8)


def words(n: int, end: str = "") -> str:
    return " ".join(f"w{i}" for i in range(n)) + end


def test_segments_end_at_a_sentence_once_past_the_target():
    text = "One two three four five six. Seven eight nine ten eleven twelve."
    segments = segment_text("v", text, RULES)
    assert [s.text for s in segments] == [
        "One two three four five six.",
        "Seven eight nine ten eleven twelve.",
    ]
    assert [s.index for s in segments] == [0, 1]
    assert [s.id for s in segments] == ["v:s0000", "v:s0001"]


def test_unpunctuated_text_splits_at_the_maximum():
    segments = segment_text("v", words(20), RULES)
    assert [len(s.text.split()) for s in segments] == [8, 8, 4]


def test_a_short_tail_folds_into_the_previous_segment():
    segments = segment_text("v", words(9), RULES)
    assert [len(s.text.split()) for s in segments] == [9]


def test_segmenting_keeps_every_word_in_order():
    text = "[Music] >> Suddenly, the climbers were flying. " + words(30)
    segments = segment_text("v", text, RULES)
    assert " ".join(s.text for s in segments) == "Suddenly, the climbers were flying. " + words(30)


def test_empty_transcript_gives_no_segments():
    assert segment_text("v", "[Music]", RULES) == []


def test_rules_are_validated():
    with pytest.raises(ValueError):
        SegmentingRules(target_words=10, max_words=5)


def test_video_from_raw_carries_metadata():
    video = video_from_raw(f.raw_video("abc"))
    assert video.id == "test-creator:abc"
    assert video.transcript_kind == "auto"
