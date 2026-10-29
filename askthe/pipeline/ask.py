"""Stage 5: answer a question from the creator's own words.

Find the relevant videos, give the model their full transcripts (with sections and
sponsor reads marked), let it reason about this question, then check every citation
in code. If any citation fails, the model gets one chance to fix them; whatever still
fails is removed and reported, never repaired.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from askthe.core.answering import (
    AnswerDraft,
    CheckedAnswer,
    answer_prompt,
    answer_system_prompt,
    check_answer,
    render_corpus,
    render_video,
    score_videos,
    select_videos,
)
from askthe.core.interfaces import (
    KnowledgeStore,
    LLMClient,
    LLMTask,
    SearchIndex,
    SearchQuery,
)
from askthe.core.models import AnswerLog, Creator
from askthe.core.profiling import PROFILER_VERSION


@dataclass
class AskResult:
    answer: CheckedAnswer
    videos_read: list[str]
    model: str
    usage: dict[str, int] = field(default_factory=dict)


def ask(
    creator: Creator,
    question: str,
    store: KnowledgeStore,
    search: SearchIndex,
    llm: LLMClient,
    budget_words: int = 400_000,
    today: date | None = None,
    log: bool = True,
) -> AskResult:
    videos = {v.id: v for v in store.list_videos(creator.slug)}
    segments = {vid: store.get_segments(vid) for vid in videos}
    words = {vid: sum(len(s.text.split()) for s in segs) for vid, segs in segments.items()}

    hits = search.search(SearchQuery(text=question, creator_id=creator.slug, limit=200))
    chosen = select_videos(words, score_videos(hits), budget_words)
    chosen.sort(key=lambda vid: (videos[vid].published_at, vid))  # stable order: cacheable

    corpus = render_corpus(
        [render_video(videos[v], store.get_profile(v), segments[v]) for v in chosen]
    )
    by_platform = {videos[v].platform_id: (videos[v], segments[v]) for v in chosen}
    system = answer_system_prompt(creator)
    prompt = answer_prompt(question, today or datetime.now(UTC).date())

    usage: dict[str, int] = {}

    def generate(p: str) -> tuple[AnswerDraft, str]:
        result = llm.generate_structured(LLMTask.ANSWER, system, p, AnswerDraft, context=corpus)
        for k, n in result.usage.items():
            usage[k] = usage.get(k, 0) + n
        return result.value, result.model

    draft, model = generate(prompt)
    checked = check_answer(draft, by_platform, creator.platform)
    if checked.problems:
        retry = (
            f"{prompt}\n\nYour previous answer had citations that could not be verified:\n"
            + "\n".join(f"- {p}" for p in checked.problems)
            + "\nAnswer again. Copy every quote exactly from the segment you cite."
        )
        draft, model = generate(retry)
        checked = check_answer(draft, by_platform, creator.platform)

    if log:
        store.log_answer(
            AnswerLog(
                id=uuid.uuid4().hex,
                creator_id=creator.slug,
                asked_at=datetime.now(UTC),
                question=question,
                answer=checked.text,
                covered=checked.coverage,
                cited_segment_ids=[i for s in checked.sources for i in s.segment_ids],
                pipeline_versions={"profiler": PROFILER_VERSION, "model": model},
            )
        )
    return AskResult(answer=checked, videos_read=chosen, model=model, usage=usage)
