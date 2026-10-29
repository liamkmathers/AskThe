"""Scoring answers against the test set (docs/EVALUATION.md). Pure logic, no I/O.

What code can check is checked here: coverage, citations, names that must appear,
whether the expected source videos were read and cited, and how much of what the
reference mode cited the other mode read. Whether an answer is *correct* stays a
person's call; each result carries `correct: null` for the reviewer to fill in.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from pydantic import BaseModel, Field

from askthe.core.models import Coverage

QUESTION_TYPES = ("lookup", "comparison", "change_of_mind", "how_to", "taste", "not_covered")


class Expected(BaseModel):
    covered: Coverage
    must_mention: list[str] = Field(default_factory=list)  # names or facts, any spelling given
    must_not_claim: list[str] = Field(default_factory=list)  # phrases that flag an error
    sources: list[str] = Field(default_factory=list)  # platform IDs of supporting videos


class TestQuestion(BaseModel):
    __test__ = False  # not a pytest class

    id: str
    question: str
    source: str | None = None  # the comment or post it came from
    type: str = "lookup"
    expected: Expected
    notes: str | None = None


class Price(BaseModel):
    """US dollars per million tokens."""

    input: float
    output: float
    cache_read: float = 0.0
    cache_write: float = 0.0


def cost(usage_by_model: dict[str, dict[str, int]], prices: dict[str, Price]) -> float | None:
    """Dollar cost of the calls, or None if any model has no price in config."""
    total = 0.0
    for model, usage in usage_by_model.items():
        price = prices.get(model)
        if price is None:
            return None
        total += sum(usage.get(k, 0) * getattr(price, k) for k in Price.model_fields) / 1e6
    return total


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def mentions(text: str, term: str) -> bool:
    """Whether `term` appears in `text`, ignoring case, accents and punctuation.
    Alternatives can be given as "Arc'teryx | Arcteryx"."""
    folded = f" {_fold(text)} "
    return any(f" {_fold(t)} " in folded for t in term.split("|") if _fold(t))


def score(
    q: TestQuestion,
    text: str,
    coverage: Coverage,
    cited_videos: Iterable[str],
    read_videos: Iterable[str],
    problems: int,
) -> dict[str, object]:
    """Automated checks for one answer. Video arguments are platform IDs."""
    cited, read = set(cited_videos), set(read_videos)
    covered = coverage is not Coverage.NONE
    expected_covered = q.expected.covered is not Coverage.NONE
    mentioned = {t: mentions(text, t) for t in q.expected.must_mention}
    flagged = [p for p in q.expected.must_not_claim if mentions(text, p)]
    return {
        "coverage_right": covered == expected_covered,
        "coverage_exact": coverage == q.expected.covered,  # full vs partial; informative
        "cited": bool(cited) if covered else True,
        "citations_hold": problems == 0,
        "must_mention": mentioned,
        "must_not_claim_found": flagged,
        "sources_read": sorted(set(q.expected.sources) & read),
        "sources_cited": sorted(set(q.expected.sources) & cited),
        "passed": (
            covered == expected_covered
            and (bool(cited) or not covered)
            and problems == 0
            and all(mentioned.values())
            and not flagged
        ),
    }


def recall(reference: Iterable[str], read: Iterable[str]) -> float | None:
    """Share of the reference's cited segments that were read; None if it cited none."""
    wanted = set(reference)
    return len(wanted & set(read)) / len(wanted) if wanted else None
