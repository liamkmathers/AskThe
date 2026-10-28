"""Turning a transcript into segments: the ordered chunks of text everything cites.

Pure functions. See docs/ARCHITECTURE.md, stage 2.
"""

from __future__ import annotations

from dataclasses import dataclass

from askthe.core import ids
from askthe.core.captions import clean_caption_text
from askthe.core.models import RawVideo, Segment, Video

SENTENCE_END = (".", "?", "!")


@dataclass(frozen=True)
class SegmentingRules:
    """Segments aim for `target_words` and never exceed `max_words`. Once past the
    target, a segment ends at the next sentence end. Auto captions have little or
    no punctuation, so those segments end at `max_words`."""

    target_words: int = 120
    max_words: int = 200

    def __post_init__(self) -> None:
        if not 0 < self.target_words <= self.max_words:
            raise ValueError("need 0 < target_words <= max_words")


def video_from_raw(raw: RawVideo) -> Video:
    meta = raw.meta
    return Video(
        id=ids.video_id(raw.creator_slug, meta.platform_id),
        creator_id=raw.creator_slug,
        platform_id=meta.platform_id,
        title=meta.title,
        description=meta.description,
        published_at=meta.published_at,
        duration_s=meta.duration_s,
        chapters=meta.chapters,
        tags=meta.tags,
        view_count=meta.view_count,
        thumbnail_url=meta.thumbnail_url,
        transcript_kind=raw.transcript.kind,
    )


def segment_text(video_id: str, text: str, rules: SegmentingRules | None = None) -> list[Segment]:
    rules = rules or SegmentingRules()
    words = clean_caption_text(text).split()

    chunks: list[list[str]] = []
    current: list[str] = []
    for word in words:
        current.append(word)
        at_sentence_end = word.endswith(SENTENCE_END)
        if len(current) >= rules.max_words or (
            len(current) >= rules.target_words and at_sentence_end
        ):
            chunks.append(current)
            current = []
    if current:
        # Fold a short tail into the previous segment rather than leave a fragment.
        if chunks and len(current) < rules.target_words // 2:
            chunks[-1].extend(current)
        else:
            chunks.append(current)

    return [
        Segment(id=ids.segment_id(video_id, i), video_id=video_id, index=i, text=" ".join(chunk))
        for i, chunk in enumerate(chunks)
    ]
