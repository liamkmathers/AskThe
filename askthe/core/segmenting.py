"""Turning caption fragments into segments: the timestamped chunks everything cites.

Pure functions. See docs/ARCHITECTURE.md, stage 2.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from askthe.core import ids
from askthe.core.captions import clean_caption_text
from askthe.core.models import CaptionFragment, Chapter, RawVideo, Segment, Video

SENTENCE_END = (".", "?", "!")


@dataclass(frozen=True)
class SegmentingRules:
    """Segments aim for `target_s` and never exceed `max_s` (unless a single fragment
    does). Once past the target, a segment ends at the next sentence end. Auto
    captions have no punctuation, so those segments end at `max_s`. Chapter starts
    always begin a new segment."""

    target_s: float = 30.0
    max_s: float = 60.0


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


def segment_fragments(
    video_id: str,
    fragments: Sequence[CaptionFragment],
    chapters: Sequence[Chapter] = (),
    rules: SegmentingRules | None = None,
) -> list[Segment]:
    rules = rules or SegmentingRules()
    cleaned = [
        (f, text)
        for f in sorted(fragments, key=lambda f: f.start_s)
        if (text := clean_caption_text(f.text))
    ]
    chapter_starts = sorted(c.start_s for c in chapters)

    groups: list[list[tuple[CaptionFragment, str]]] = []
    current: list[tuple[CaptionFragment, str]] = []
    for fragment, text in cleaned:
        if current and _should_break(current, fragment, chapter_starts, rules):
            groups.append(current)
            current = []
        current.append((fragment, text))
    if current:
        groups.append(current)

    segments = []
    for index, group in enumerate(groups):
        start = group[0][0].start_s
        last = group[-1][0]
        end = last.start_s + last.duration_s
        if index + 1 < len(groups):
            # Auto captions often overlap; never run past the next segment's start.
            end = min(end, groups[index + 1][0][0].start_s)
        segments.append(
            Segment(
                id=ids.segment_id(video_id, index),
                video_id=video_id,
                start_s=start,
                end_s=max(end, start),
                text=" ".join(text for _, text in group),
                chapter=_chapter_at(start, chapters),
            )
        )
    return segments


def _should_break(
    current: list[tuple[CaptionFragment, str]],
    upcoming: CaptionFragment,
    chapter_starts: list[float],
    rules: SegmentingRules,
) -> bool:
    start = current[0][0].start_s
    if any(start < c <= upcoming.start_s for c in chapter_starts):
        return True
    elapsed = upcoming.start_s - start
    if elapsed >= rules.max_s:
        return True
    return elapsed >= rules.target_s and current[-1][1].endswith(SENTENCE_END)


def _chapter_at(t: float, chapters: Sequence[Chapter]) -> str | None:
    title = None
    for chapter in sorted(chapters, key=lambda c: c.start_s):
        if chapter.start_s <= t:
            title = chapter.title
    return title
