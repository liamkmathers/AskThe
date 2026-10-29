"""Answering: choose which videos to read, lay them out for the model, and check its
answer.

The model reasons over the creator's actual words at question time (D15). This module
decides what it reads and verifies what it cites: every quote must really appear in
the segment it names, or the citation is rejected. Nothing here calls the model.

Pure functions only: no I/O, no LLM calls.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from pydantic import BaseModel, Field

from askthe.core import ids
from askthe.core.interfaces import SearchHit
from askthe.core.models import Coverage, Creator, Passage, Segment, Video, VideoProfile
from askthe.core.profiling import normalise

WATCH_URLS = {"youtube": "https://www.youtube.com/watch?v={}"}


def watch_url(platform: str, platform_id: str) -> str:
    return WATCH_URLS[platform].format(platform_id)


# --- Choosing what to read ------------------------------------------------------


def score_videos(hits: Sequence[SearchHit], per_video: int = 5) -> dict[str, float]:
    """A video's relevance: the sum of its best few search hits."""
    by_video: dict[str, list[float]] = defaultdict(list)
    for hit in hits:
        by_video[hit.video_id].append(hit.score)
    return {v: sum(sorted(s, reverse=True)[:per_video]) for v, s in by_video.items()}


def select_videos(
    words: Mapping[str, int], scores: Mapping[str, float], budget_words: int
) -> list[str]:
    """Video IDs to read for a question.

    If everything fits in the budget, read everything: the model sees the whole
    catalogue, and the same input every time means it's served from cache. Otherwise
    take the most relevant videos that fit.
    """
    if sum(words.values()) <= budget_words:
        return list(words)
    chosen, used = [], 0
    for video_id in sorted(scores, key=lambda v: -scores[v]):
        size = words.get(video_id, 0)
        if size and used + size <= budget_words:
            chosen.append(video_id)
            used += size
    return chosen


# --- Laying videos out for the model ------------------------------------------------


def _words_pattern(phrase: str) -> re.Pattern[str] | None:
    words = re.findall(r"\w+", phrase)
    if not words:
        return None
    return re.compile(r"\W+".join(re.escape(w) for w in words), re.IGNORECASE)


def mark_passages(
    segments: Sequence[Segment], passages: Sequence[Passage]
) -> tuple[dict[int, str], list[Passage]]:
    """Segment texts with passage markers inserted at the passage's exact first and
    last words, plus the passages that couldn't be located (reported, never guessed)."""
    texts = {s.index: s.text for s in segments}
    unlocated = []
    # Insert from the end of the transcript backwards so earlier positions stay valid.
    for p in sorted(passages, key=lambda p: (p.first_segment, p.last_segment), reverse=True):
        start_pat, end_pat = _words_pattern(p.starts_with), _words_pattern(p.ends_with)
        start_text, end_text = texts.get(p.first_segment), texts.get(p.last_segment)
        start = start_pat.search(start_text) if start_pat and start_text else None
        end = end_pat.search(end_text) if end_pat and end_text else None
        if p.first_segment == p.last_segment and start and end and end.end() < start.start():
            end = None
        if not (start and end):
            unlocated.append(p)
            continue
        label = p.role.value.upper()
        note = f": {p.note}" if p.note else ""
        end_text = f"{end_text[: end.end()]} «END {label}»{end_text[end.end() :]}"
        texts[p.last_segment] = end_text
        start_text = texts[p.first_segment]
        texts[p.first_segment] = (
            f"{start_text[: start.start()]}«{label}{note}» {start_text[start.start() :]}"
        )
    return texts, unlocated


def render_video(
    video: Video,
    profile: VideoProfile | None,
    segments: Sequence[Segment],
    only: Sequence[int] | None = None,
) -> str:
    """One video as the model reads it: what it is, its sections, then the transcript.

    Segments are labelled [platform_id:index] so citations can name them. Sponsor reads,
    asides, intro and outro are marked inline with «...» markers. With `only`, just
    those segments are shown and skipped stretches are marked, so the model knows the
    transcript is partial.
    """
    lines = [
        f'<video id="{video.platform_id}">',
        f"Title: {video.title}",
        f"Published: {video.published_at.date().isoformat()}",
    ]
    texts = {s.index: s.text for s in segments}
    if profile:
        lines += [f"Type: {profile.video_type.value}", f"Purpose: {profile.purpose}"]
        if profile.outline:
            lines.append("Sections:")
            lines += [
                f"- [{s.first_segment}-{s.last_segment}] {s.title}: {s.summary}".rstrip(": ")
                for s in profile.outline
            ]
        texts, unlocated = mark_passages(segments, profile.passages)
        for p in unlocated:
            lines.append(
                f"Note: a {p.role.value} passage ({p.note or 'unlabelled'}) is somewhere in "
                f"segments {p.first_segment}-{p.last_segment}; its exact bounds are unknown."
            )
        for c in profile.corrections:
            lines.append(f"Correction at {c.segment_id.rsplit(':', 1)[-1]}: {c.note}")
    shown = sorted(texts) if only is None else sorted(i for i in set(only) if i in texts)
    lines.append("Transcript:" if only is None else "Transcript (relevant parts only):")
    previous = -1
    for i in shown:
        if only is not None and i > previous + 1:
            lines.append(f"[... segments {previous + 1}-{i - 1} not shown ...]")
        lines.append(f"[{video.platform_id}:{i}] {texts[i]}")
        previous = i
    if only is not None and texts and previous < max(texts):
        lines.append(f"[... segments {previous + 1}-{max(texts)} not shown ...]")
    lines.append("</video>")
    return "\n".join(lines)


def render_corpus(blocks: Sequence[str]) -> str:
    return "<videos>\n" + "\n\n".join(blocks) + "\n</videos>"


# --- Instructions ---------------------------------------------------------------


def answer_system_prompt(creator: Creator) -> str:
    """Stable per creator, so it can be cached across every question."""
    who, pron = creator.refer_to_creator_as, creator.pronoun
    return f"""You answer fans' questions about what {creator.display_name} \
({creator.niche}) has said in their videos. You are given the transcripts of the \
relevant videos, in full or as the relevant parts. Answer from them only.

How to answer:
1. His opinion is the point. Lead with what {who} thinks, prefers, wears and \
recommends, and why, in plain language. His personal taste is exactly what fans want; \
present it confidently as his taste.
2. Grounded or silent. Use only what is in the transcripts. If he hasn't covered \
something, say so plainly; never fill gaps from general knowledge. If he covered part \
of the question, answer that part and say what's missing.
3. Cite everything. Every statement about what he said gets a citation marker like \
[1], pointing to a citation with the video id, the segment number and a short quote \
copied exactly from that segment.
4. Newest first. Videos have publish dates. Lead with his most recent view; if he \
changed his mind, or the product changed, say so and cite both.
5. Third person. Describe what {who} says ("{pron} recommends..."). Never write as him \
or imitate his voice.
6. Sponsorship. Text inside «SPONSOR ...» markers is a paid read. Never present it as \
his independent opinion; if it is relevant, say it was sponsored. What he says about \
his own products or brand is his opinion.
7. Attribute. Facts and history are what he says, not verified truth. Views he reports \
from others ("people say...", a brand's own claim) are theirs, not his. Keep his \
hedging ("he thinks", "he isn't sure"); never strengthen it.
8. Nothing about his personal life, family or friends. Skits and jokes («ASIDE») are \
not opinions unless they contain a real claim about the subject.
9. Names: use the names in the transcripts and section notes; never guess what an \
unnamed product is.
10. Be concise: a direct answer first, then the reasoning and any nuance."""


def answer_prompt(question: str, today: date) -> str:
    return f"""Today is {today.isoformat()}.

Question: {question}"""


# --- What the model returns, and checking it -----------------------------------------


class CitationDraft(BaseModel):
    n: int = Field(description="The number used in the answer's [n] marker.")
    video: str = Field(description="The video id, from <video id=...>.")
    segment: int = Field(description="The segment number the quote is in.")
    quote: str = Field(description="A short quote copied exactly from that segment.")


class AnswerDraft(BaseModel):
    answer: str = Field(description="The answer, in Markdown, with [n] citation markers.")
    coverage: Coverage = Field(
        description="full: answered; partial: some of it; none: he hasn't covered it."
    )
    citations: list[CitationDraft]


@dataclass(frozen=True)
class Source:
    n: int
    video_id: str
    title: str
    published: date
    url: str
    segment_ids: list[str]
    quote: str


@dataclass
class CheckedAnswer:
    text: str
    coverage: Coverage
    sources: list[Source] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def quote_location(quote: str, segment_index: int, segments: Sequence[Segment]) -> list[int]:
    """Segments the quote appears in, starting at the cited one; [] if it isn't there.
    A quote may run on into the next segment, so that pair is also checked."""
    wanted = normalise(quote)
    by_index = {s.index: s for s in segments}
    cited = by_index.get(segment_index)
    if not wanted or cited is None:
        return []
    if wanted in normalise(cited.text):
        return [segment_index]
    following = by_index.get(segment_index + 1)
    if following and wanted in normalise(f"{cited.text} {following.text}"):
        return [segment_index, segment_index + 1]
    return []


def check_answer(
    draft: AnswerDraft,
    videos: Mapping[str, tuple[Video, Sequence[Segment]]],
    platform: str,
) -> CheckedAnswer:
    """Verify every citation against the transcripts. Failed citations are reported
    and their markers removed from the text; nothing is repaired or guessed."""
    checked = CheckedAnswer(text=draft.answer, coverage=draft.coverage)
    for c in draft.citations:
        found = videos.get(c.video)
        located = quote_location(c.quote, c.segment, found[1]) if found else []
        if not located:
            where = f"{c.video}:{c.segment}" if found else f"unknown video {c.video!r}"
            checked.problems.append(f"[{c.n}] quote not found in {where}: {c.quote[:80]!r}")
            checked.text = checked.text.replace(f"[{c.n}]", "")
            continue
        video = found[0]
        checked.sources.append(
            Source(
                n=c.n,
                video_id=video.id,
                title=video.title,
                published=video.published_at.date(),
                url=watch_url(platform, video.platform_id),
                segment_ids=[ids.segment_id(video.id, i) for i in located],
                quote=c.quote,
            )
        )
    if checked.coverage is not Coverage.NONE and not checked.sources:
        checked.problems.append("answer claims coverage but has no verified citations")
    return checked
