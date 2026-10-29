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


DESCRIPTION = -1  # the "segment" number a citation uses for the video's description
_URL = re.compile(r"https?://\S+")


def clean_description(text: str) -> str:
    """The description as the model reads it: links collapsed, blank runs squeezed."""
    text = _URL.sub("<link>", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def render_video(
    video: Video,
    profile: VideoProfile | None,
    segments: Sequence[Segment],
    only: Sequence[int] | None = None,
) -> str:
    """One video as the model reads it: what it is, its sections, then the transcript.

    Segments are labelled [platform_id:index] so citations can name them; the
    description, which he wrote, is labelled [platform_id:-1]. Sponsor reads,
    asides, intro and outro are marked inline with «...» markers. With `only`, just
    those segments are shown and skipped stretches are marked, so the model knows the
    transcript is partial.
    """
    lines = [
        f'<video id="{video.platform_id}">',
        f"Title: {video.title}",
        f"Published: {video.published_at.date().isoformat()}",
    ]
    description = clean_description(video.description)
    if description:
        lines += [
            "Description (written by him; promo codes, sponsor and affiliate mentions in it "
            "are advertising, not verdicts):",
            f"[{video.platform_id}:{DESCRIPTION}] {description}",
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
    if not blocks:  # nothing matched: say so, rather than send an empty corpus
        return "<videos>\nNothing in his videos matched this question.\n</videos>"
    return "<videos>\n" + "\n\n".join(blocks) + "\n</videos>"


# --- Instructions ---------------------------------------------------------------


def answer_system_prompt(creator: Creator) -> str:
    """Stable per creator, so it can be cached across every question."""
    who, pron = creator.refer_to_creator_as, creator.pronoun
    return f"""You answer fans' questions about what {creator.display_name} \
({creator.niche}) has said in their videos. You are given the relevant videos: each \
one's description (which he wrote) and its transcript, in full or as the relevant \
parts. Answer from them only.

How to answer:
1. His opinion is the point. Lead with what {who} thinks, prefers, wears and \
recommends, and why, in plain language. His personal taste is exactly what fans want; \
present it confidently as his taste.
2. Grounded or silent. Use only what he says in the transcripts and wrote in the \
descriptions; never fill gaps from general knowledge. You may apply his stated advice \
to the fan's own details (his "two sizes up" to their size, say), as long as it's \
clearly his rule applied. If he covered part of the question, answer that part and \
say plainly what he hasn't covered.
3. Not covered. If nothing he said answers the question, say so in a sentence or two: \
"{who} hasn't covered X in the videos available here." At most, point to the closest \
thing he did cover, in a line, cited. Don't build an answer from loosely related \
material, and never mention transcripts, excerpts, segments or what you were given, \
and never ask the fan to supply a video: speak about his videos, not your inputs.
4. Cite everything. Every statement about what he said gets a citation marker like \
[1], pointing to a citation with the video id, the segment number (-1 for the \
description) and a short quote copied exactly from it. Section summaries and notes \
are only there to help you find things; they are not his words, so never state \
something that appears only there.
5. Newest first, with nuance. Videos have publish dates. Lead with his most recent \
view; if he changed his mind, or the product changed, say so and cite both. When his \
views are mixed, give the general lean ("mostly yes, but...") and then his dated \
opinions; not everything he says is black and white, and you needn't force it to be.
6. Third person. Describe what {who} says ("{pron} recommends..."). Never write as him \
or imitate his voice.
7. Sponsorship. Text inside «SPONSOR ...» markers is a paid read, and so are promo \
codes and sponsor mentions in descriptions. Never present it as his independent \
opinion; if it is relevant, say it was sponsored. What he says about \
his own products or brand is his opinion.
8. Attribute. Facts and history are what he says, not verified truth. Views he reports \
from others ("people say...", a brand's own claim) are theirs, not his. Keep his \
hedging ("he thinks", "he isn't sure"); never strengthen it.
9. Nothing about his personal life, family or friends. Never mention them, even in \
passing or to explain a choice: say "he's cutting down his collection", not why his \
home life led to it, and "a pair he's seen worn a lot", not whose. If a question is \
about his personal life, decline briefly and offer a question about his videos \
instead. Skits and jokes («ASIDE») are not opinions unless they contain a real claim \
about the subject. If the question assumes something he didn't say, say what he \
actually said.
10. Names: use the names in the transcripts, descriptions and section notes; never \
guess what an unnamed product is.
11. Length follows the question: a direct answer first, then the reasoning and \
nuance. A question about several products earns a short part on each; a simple one \
gets a short answer. Keep it readable, in Markdown: open with the direct answer in \
one or two sentences; give each product, part of the question or period of his views \
its own short paragraph or bullet list, with a bold label when there are several; no \
wall of text and no padding."""


def answer_prompt(question: str, today: date) -> str:
    return f"""Today is {today.isoformat()}.

Question: {question}"""


# --- What the model returns, and checking it -----------------------------------------


class CitationDraft(BaseModel):
    n: int = Field(description="The number used in the answer's [n] marker.")
    video: str = Field(description="The video id, from <video id=...>.")
    segment: int = Field(
        description="The segment number the quote is in, or -1 for the video's description."
    )
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
    in_description: bool = False  # quoted from the video's description, not the video


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
        if found and c.segment == DESCRIPTION:
            quoted = normalise(c.quote)
            shown = normalise(clean_description(found[0].description))
            located = [DESCRIPTION] if quoted and quoted in shown else []
        else:
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
                segment_ids=[ids.segment_id(video.id, i) for i in located if i != DESCRIPTION],
                quote=c.quote,
                in_description=located == [DESCRIPTION],
            )
        )
    if checked.coverage is not Coverage.NONE and not checked.sources:
        checked.problems.append("answer claims coverage but has no verified citations")
    return checked
