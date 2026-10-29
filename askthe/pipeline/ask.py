"""Stage 5: answer a question from the creator's own words.

Two ways to choose what the model reads, set in askthe.toml under [retrieval]:

- "hybrid" (default): plan queries, search keyword and vector indexes, fuse, rerank,
  and assemble the relevant sections of the relevant videos (core/retrieval.py).
- "full": read whole transcripts, every video if the catalogue fits the budget. Simple
  and complete for small catalogues; the reference hybrid is measured against.

Either way the model reasons about this question over the creator's actual words
(D15), and every citation is checked in code. If any fails, the model gets one chance
to fix it; whatever still fails is removed and reported, never repaired.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

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
from askthe.core.chunking import chunk_header
from askthe.core.interfaces import (
    DocKind,
    Embedder,
    EmbeddingError,
    KnowledgeStore,
    LLMClient,
    LLMTask,
    SearchIndex,
    SearchQuery,
    VectorIndex,
)
from askthe.core.models import AnswerLog, Creator, Segment, Video
from askthe.core.profiling import PROFILER_VERSION
from askthe.core.retrieval import (
    RERANK_SYSTEM,
    Pick,
    QueryPlan,
    RerankDraft,
    expand_to_sections,
    name_variants,
    plan_prompt,
    plan_system_prompt,
    reciprocal_rank_fusion,
    rerank_prompt,
    top,
)


@dataclass(frozen=True)
class RetrievalSettings:
    mode: str = "hybrid"  # "hybrid" or "full"
    full_budget_words: int = 400_000  # "full": read everything if under this
    context_words: int = 12_000  # "hybrid": words of transcript given to the model
    per_query: int = 40  # "hybrid": hits taken from each search, per query
    candidates: int = 60  # "hybrid": fused candidates sent to the reranker
    broad_candidates: int = 100  # ... when the question needs a catalogue sweep
    min_score: int = 2  # "hybrid": lowest rerank score kept (0-3)

    @classmethod
    def from_config(cls, values: dict[str, Any]) -> RetrievalSettings:
        return cls(**values)


@dataclass
class AskResult:
    answer: CheckedAnswer
    videos_read: list[str]
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    usage_by_model: dict[str, dict[str, int]] = field(default_factory=dict)  # for costing
    segments_read: list[str] = field(default_factory=list)  # IDs of every segment shown
    trace: dict[str, Any] = field(default_factory=dict)  # how the context was chosen


def ask(
    creator: Creator,
    question: str,
    store: KnowledgeStore,
    search: SearchIndex,
    llm: LLMClient,
    vectors: VectorIndex | None = None,
    embedder: Embedder | None = None,
    settings: RetrievalSettings | None = None,
    today: date | None = None,
    log: bool = True,
) -> AskResult:
    settings = settings or RetrievalSettings()
    videos = {v.id: v for v in store.list_videos(creator.slug)}
    segments = {vid: store.get_segments(vid) for vid in videos}
    profiles = {vid: store.get_profile(vid) for vid in videos}
    usage: dict[str, int] = {}
    usage_by_model: dict[str, dict[str, int]] = {}
    trace: dict[str, Any] = {"mode": settings.mode, "warnings": []}

    def add_usage(u: dict[str, int], model: str) -> None:
        per_model = usage_by_model.setdefault(model, {})
        for k, n in u.items():
            usage[k] = usage.get(k, 0) + n
            per_model[k] = per_model.get(k, 0) + n

    if settings.mode == "full":
        shown = _full_context(question, videos, segments, search, creator, settings)
    elif settings.mode == "hybrid":
        if vectors is None or embedder is None:
            raise ValueError("hybrid retrieval needs a vector index and an embedder")
        shown = _hybrid_context(
            question,
            creator,
            videos,
            segments,
            profiles,
            store,
            search,
            vectors,
            embedder,
            llm,
            settings,
            add_usage,
            trace,
        )
    else:
        raise ValueError(f"unknown retrieval mode {settings.mode!r}")

    chosen = sorted(shown, key=lambda vid: (videos[vid].published_at, vid))  # stable order
    corpus = render_corpus(
        [render_video(videos[v], profiles[v], segments[v], only=shown[v]) for v in chosen]
    )
    trace["context_words"] = sum(
        len(s.text.split())
        for v in chosen
        for s in segments[v]
        if shown[v] is None or s.index in shown[v]
    )
    by_platform = {videos[v].platform_id: (videos[v], segments[v]) for v in chosen}
    system = answer_system_prompt(creator)
    prompt = answer_prompt(question, today or datetime.now(UTC).date())

    # Full mode sends the same corpus with every question, so it goes in `context`,
    # which adapters cache. Hybrid's passages differ per question: caching them would
    # cost more than plain input and never be read back, so they go in the prompt.
    shared = settings.mode == "full"

    def generate(p: str) -> tuple[AnswerDraft, str]:
        result = llm.generate_structured(
            LLMTask.ANSWER,
            system,
            p if shared else f"{corpus}\n\n{p}",
            AnswerDraft,
            context=corpus if shared else None,
        )
        add_usage(result.usage, result.model)
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
                pipeline_versions={
                    "profiler": PROFILER_VERSION,
                    "model": model,
                    "retrieval": settings.mode,
                },
            )
        )
    return AskResult(
        answer=checked,
        videos_read=chosen,
        model=model,
        usage=usage,
        usage_by_model=usage_by_model,
        segments_read=[
            s.id for v in chosen for s in segments[v] if shown[v] is None or s.index in shown[v]
        ],
        trace=trace,
    )


def _full_context(
    question: str,
    videos: dict[str, Video],
    segments: dict[str, list[Segment]],
    search: SearchIndex,
    creator: Creator,
    settings: RetrievalSettings,
) -> dict[str, list[int] | None]:
    words = {vid: sum(len(s.text.split()) for s in segs) for vid, segs in segments.items()}
    hits = search.search(SearchQuery(text=question, creator_id=creator.slug, limit=200))
    chosen = select_videos(words, score_videos(hits), settings.full_budget_words)
    return {vid: None for vid in chosen}  # None: the whole transcript


def _hybrid_context(
    question: str,
    creator: Creator,
    videos: dict[str, Video],
    segments: dict[str, list[Segment]],
    profiles: dict[str, Any],
    store: KnowledgeStore,
    search: SearchIndex,
    vectors: VectorIndex,
    embedder: Embedder,
    llm: LLMClient,
    settings: RetrievalSettings,
    add_usage: Any,
    trace: dict[str, Any],
) -> dict[str, list[int] | None]:
    # 1. Plan.
    planned = llm.generate_structured(
        LLMTask.PLAN, plan_system_prompt(creator), plan_prompt(question), QueryPlan
    )
    add_usage(planned.usage, planned.model)
    plan = planned.value
    names = name_variants(plan.names, creator, store.list_entities(creator.slug))
    queries = list(dict.fromkeys([question, *plan.queries, *names]))
    trace.update(queries=queries, broad=plan.broad)

    # 2. Search keyword and vector indexes for every query, and fuse.
    segment_kinds = [DocKind.SEGMENT]
    video_kinds = [DocKind.PROFILE, DocKind.PROFILE_QUESTION]
    rankings: list[list[str]] = []
    video_rankings: list[list[str]] = []
    for q in queries:
        rankings.append(
            [
                h.doc_id
                for h in search.search(
                    SearchQuery(
                        text=q,
                        creator_id=creator.slug,
                        kinds=segment_kinds,
                        limit=settings.per_query,
                    )
                )
            ]
        )
        video_rankings.append(
            [
                h.video_id
                for h in search.search(
                    SearchQuery(text=q, creator_id=creator.slug, kinds=video_kinds, limit=20)
                )
            ]
        )
    try:
        query_vectors = embedder.embed(queries)
    except EmbeddingError as e:
        trace["warnings"].append(f"vector search skipped, keyword only: {e}")
        query_vectors = []
    for v in query_vectors:
        rankings.append(
            [h.doc_id for h in vectors.search(v, creator.slug, segment_kinds, settings.per_query)]
        )
        video_rankings.append(
            [h.video_id for h in vectors.search(v, creator.slug, video_kinds, 20)]
        )

    fused = reciprocal_rank_fusion(rankings)
    # A video whose profile matches the question lends weight to its passages.
    video_boost = reciprocal_rank_fusion(video_rankings)
    by_id = {s.id: (vid, s) for vid, segs in segments.items() for s in segs}
    for doc_id in list(fused):
        if doc_id in by_id:
            fused[doc_id] += 0.5 * video_boost.get(by_id[doc_id][0], 0.0)
    limit = settings.broad_candidates if plan.broad else settings.candidates
    candidates = [d for d in top(fused, limit) if d in by_id]
    trace["candidates"] = len(candidates)
    if not candidates:
        return {}

    # 3. Rerank.
    passages = [
        f"{chunk_header(videos[by_id[d][0]], profiles[by_id[d][0]], by_id[d][1].index)}\n"
        f"{by_id[d][1].text}"
        for d in candidates
    ]
    reranked = llm.generate_structured(
        LLMTask.RERANK, RERANK_SYSTEM, rerank_prompt(question, passages), RerankDraft
    )
    add_usage(reranked.usage, reranked.model)
    scores = {s.n: s.score for s in reranked.value.scores if 0 <= s.n < len(candidates)}
    picks = [
        Pick(
            video_id=by_id[d][0], segment_index=by_id[d][1].index, score=scores[i] + fused[d]
        )  # rerank score first, fusion breaks ties
        for i, d in enumerate(candidates)
        if scores.get(i, 0) >= settings.min_score
    ]
    trace["kept"] = len(picks)

    # 4. Assemble sections within the word budget.
    shown = expand_to_sections(picks, profiles, segments, settings.context_words)
    return dict(shown.items())
