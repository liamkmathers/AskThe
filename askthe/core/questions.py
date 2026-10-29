"""Picking fan questions out of viewers' comments, for the test set (M4).

Pure heuristics, tuned for recall: a person reviews the candidates and picks the test
set, so letting through some non-questions is cheaper than missing real ones. Comments
asking for a video ("can you review X?") are kept as requests: they point at topics he
may not have covered, which the test set needs.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from pydantic import BaseModel

from askthe.core.models import RawComments

_STARTERS = (
    "what",
    "which",
    "how",
    "is",
    "are",
    "does",
    "do",
    "did",
    "should",
    "would",
    "can",
    "could",
    "any",
    "where",
    "why",
    "will",
    "have",
    "has",
    "thoughts",
    "opinion",
    "recommend",
)
_QUESTION_PHRASES = re.compile(
    r"\b(thoughts on|opinion on|worth it|vs\.?|versus|recommend|any recs|which one|"
    r"is it worth|should i)\b",
    re.IGNORECASE,
)
_REQUEST = re.compile(
    r"\b(review|video on|video about|do a video|make a video|cover|please do|"
    r"next video|part 2|part two|you should (try|test|do))\b",
    re.IGNORECASE,
)
_URL = re.compile(r"https?://\S+")
_TIMESTAMP = re.compile(r"^\s*\d{1,2}:\d{2}")


class QuestionCandidate(BaseModel):
    id: str  # the comment ID
    question: str  # verbatim
    kind: str  # "question" or "request"
    likes: int
    video: str  # platform ID of the video it was posted on
    video_title: str
    url: str


def is_question(text: str) -> bool:
    first = text.strip().split(maxsplit=1)[0].lower().strip(",.!:") if text.strip() else ""
    return "?" in text or first in _STARTERS or bool(_QUESTION_PHRASES.search(text))


def question_candidates(
    batches: Iterable[RawComments],
    titles: dict[str, str],
    url_for: dict[str, str],
    min_words: int = 4,
    max_words: int = 80,
) -> list[QuestionCandidate]:
    """Question-like comments by viewers, most liked first, near-duplicates dropped.

    `url_for` maps a video's platform ID to its URL; the comment ID is appended so the
    link opens the comment itself.
    """
    found: list[QuestionCandidate] = []
    seen: set[str] = set()
    for batch in batches:
        for c in batch.comments:
            text = " ".join(c.text.split())
            words = text.split()
            if c.by_creator or not (min_words <= len(words) <= max_words):
                continue
            if _TIMESTAMP.match(text) or len(_URL.findall(text)) > 0:
                continue
            if not is_question(text):
                continue
            key = re.sub(r"[^a-z0-9 ]", "", text.lower())[:80]
            if key in seen:
                continue
            seen.add(key)
            found.append(
                QuestionCandidate(
                    id=c.id,
                    question=text,
                    kind="request" if _REQUEST.search(text) else "question",
                    likes=c.like_count,
                    video=batch.platform_id,
                    video_title=titles.get(batch.platform_id, ""),
                    url=f"{url_for[batch.platform_id]}&lc={c.id}",
                )
            )
    return sorted(found, key=lambda q: (-q.likes, q.video, q.id))
