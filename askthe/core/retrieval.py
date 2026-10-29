"""Hybrid retrieval: from a question to the passages worth reading.

1. Plan: the question becomes several search queries plus the names it involves,
   expanded with known aliases and caption misspellings.
2. Search: every query runs against keyword search (BM25) and vector search
   (embeddings); the ranked lists are fused with reciprocal rank fusion.
3. Rerank: a model scores the top candidates for relevance to the question.
4. Assemble: kept passages expand to their surrounding section, grouped by video and
   ordered by date, within a word budget.

The model then reasons over that context (D15). Pure functions only: no I/O.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pydantic import BaseModel, Field

from askthe.core.models import Creator, Entity, Segment, VideoProfile
from askthe.core.profiling import glossary_text, normalise

# --- 1. Plan ----------------------------------------------------------------------


class QueryPlan(BaseModel):
    queries: list[str] = Field(
        description="3 to 6 search queries: rephrasings, synonyms and the specific things "
        "the answer would mention (materials, conditions, product types)."
    )
    names: list[str] = Field(description="Products, brands or people the question names.")
    broad: bool = Field(
        description="True if answering needs a sweep of everything he has covered "
        '("best X he has reviewed", "which brands does he like"), not a few passages.'
    )


def plan_system_prompt(creator: Creator) -> str:
    return f"""You turn a fan's question into search queries over transcripts of \
{creator.display_name}'s videos ({creator.niche}). The transcripts are spoken and \
informal, so include the plain words he would say ("kept me warm", "fell apart"), not \
just formal terms. Correct names to the glossary spelling.

Glossary of known names:
{glossary_text(creator) or "(none)"}"""


def plan_prompt(question: str) -> str:
    return f"Question: {question}"


def name_variants(names: Sequence[str], creator: Creator, entities: Sequence[Entity]) -> list[str]:
    """Each name plus the aliases and caption misspellings known for it."""
    known: dict[str, list[str]] = {}
    for g in creator.glossary:
        known[normalise(g.name)] = [g.name, *g.heard_as]
    for e in entities:
        known.setdefault(normalise(e.canonical_name), []).extend([e.canonical_name, *e.aliases])
    out: list[str] = []
    for name in names:
        key = normalise(name)
        matches = [v for k, vs in known.items() if key and (key in k or k in key) for v in vs]
        out += [name, *matches]
    return list(dict.fromkeys(n for n in out if n.strip()))


# --- 2. Fuse ----------------------------------------------------------------------


def reciprocal_rank_fusion(rankings: Sequence[Sequence[str]], k: int = 60) -> dict[str, float]:
    """Combine ranked lists: each appearance adds 1 / (k + rank). Robust to the very
    different score scales of keyword and vector search."""
    scores: dict[str, float] = defaultdict(float)
    for ranking in rankings:
        for rank, doc_id in enumerate(dict.fromkeys(ranking), start=1):
            scores[doc_id] += 1.0 / (k + rank)
    return dict(scores)


def top(scores: Mapping[str, float], n: int) -> list[str]:
    return [d for d, _ in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:n]]


# --- 3. Rerank --------------------------------------------------------------------


class PassageScore(BaseModel):
    n: int = Field(description="The passage number.")
    score: int = Field(
        description="3: directly answers; 2: relevant evidence; 1: related context; "
        "0: not relevant."
    )


class RerankDraft(BaseModel):
    scores: list[PassageScore]


RERANK_SYSTEM = """You judge which transcript passages help answer a fan's question \
about a creator's videos. Score every passage. Passages giving the creator's own \
opinion, preference, test or recommendation on the subject are the most useful. A \
passage marked as a sponsor read is relevant only if the question is about that \
sponsor or product."""


def rerank_prompt(question: str, passages: Sequence[str], max_words: int = 220) -> str:
    def clip(text: str) -> str:
        words = text.split()
        return " ".join(words[:max_words]) + (" ..." if len(words) > max_words else "")

    numbered = "\n\n".join(
        f"<passage n={i}>\n{clip(p)}\n</passage>" for i, p in enumerate(passages)
    )
    return f"Question: {question}\n\n{numbered}"


# --- 4. Assemble ------------------------------------------------------------------


@dataclass(frozen=True)
class Pick:
    video_id: str
    segment_index: int
    score: float  # higher is more relevant


def expand_to_sections(
    picks: Sequence[Pick],
    profiles: Mapping[str, VideoProfile | None],
    segments: Mapping[str, Sequence[Segment]],
    budget_words: int,
    max_section_segments: int = 6,
    neighbours: int = 1,
) -> dict[str, list[int]]:
    """Segment indexes to show per video.

    Each pick brings its whole section when the section is short, otherwise the pick
    and its neighbours, so a passage is read with what leads into and out of it.
    Picks are taken best first until the word budget is spent.
    """
    words = {(v, s.index): len(s.text.split()) for v, segs in segments.items() for s in segs}
    chosen: dict[str, set[int]] = defaultdict(set)
    used = 0
    for pick in sorted(picks, key=lambda p: -p.score):
        count = len(segments.get(pick.video_id, ()))
        if not count:
            continue
        span = _span(pick, profiles.get(pick.video_id), count, max_section_segments, neighbours)
        new = [i for i in span if i not in chosen[pick.video_id]]
        cost = sum(words.get((pick.video_id, i), 0) for i in new)
        if used and used + cost > budget_words:
            continue
        chosen[pick.video_id].update(new)
        used += cost
    return {v: sorted(ix) for v, ix in chosen.items() if ix}


def _span(
    pick: Pick, profile: VideoProfile | None, count: int, max_section: int, neighbours: int
) -> range:
    if profile:
        for s in profile.outline:
            if s.first_segment <= pick.segment_index <= s.last_segment:
                if s.last_segment - s.first_segment + 1 <= max_section:
                    return range(s.first_segment, min(s.last_segment, count - 1) + 1)
                break
    lo = max(pick.segment_index - neighbours, 0)
    hi = min(pick.segment_index + neighbours, count - 1)
    return range(lo, hi + 1)
