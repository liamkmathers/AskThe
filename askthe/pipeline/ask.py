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
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from askthe.core.answering import (
    AnswerDraft,
    CheckedAnswer,
    answer_prompt,
    answer_system_prompt,
    check_answer,
    partial_answer,
    render_corpus,
    render_video,
    score_videos,
    select_videos,
    sponsor_read_texts,
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
    named_in,
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
    # "hybrid": candidates that name a product the question names are kept even if the
    # reranker scored them low (brief mentions, often his newest word), this many per
    # video and in all, after everything the reranker kept.
    named_per_video: int = 2
    named_total: int = 8
    # Answer only from profiled videos: without a profile, sponsor reads and asides
    # aren't marked (rules 6 and 8), so an unprofiled video waits for `understand`.
    require_profiles: bool = False
    # Off only to measure what profiles add (`askthe eval --no-profiles`): answers then
    # see no sections, profile documents, extracted entities or sponsor markings.
    use_profiles: bool = True

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
    answer_id: str | None = None  # set when the answer was saved


# Progress for a live page: ("searching", {}), ("reading", {"videos": [...]}),
# ("writing", {"text": answer so far}), ("retrying", {}) when citations failed and the
# answer is being written again.
OnEvent = Callable[[str, dict[str, Any]], None]


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
    on_event: OnEvent | None = None,
    parent_id: str | None = None,
) -> AskResult:
    """Answer one question. `on_event` reports progress and streams the answer text;
    `parent_id` records the answer this one follows up (for a later chat thread)."""
    settings = settings or RetrievalSettings()
    emit = on_event or (lambda kind, data: None)
    emit("searching", {})
    profiles = {v.id: store.get_profile(v.id) for v in store.list_videos(creator.slug)}
    videos = {
        v.id: v
        for v in store.list_videos(creator.slug)
        if profiles[v.id] or not settings.require_profiles
    }
    if not settings.use_profiles:
        profiles = dict.fromkeys(profiles)
    segments = {vid: store.get_segments(vid) for vid in videos}
    usage: dict[str, int] = {}
    usage_by_model: dict[str, dict[str, int]] = {}
    trace: dict[str, Any] = {
        "mode": settings.mode,
        "profiles": settings.use_profiles,
        "warnings": [],
    }

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
        [
            render_video(
                videos[v], profiles[v], segments[v], only=shown[v], description=creator.own_uploads
            )
            for v in chosen
        ]
    )
    trace["context_words"] = sum(
        len(s.text.split())
        for v in chosen
        for s in segments[v]
        if shown[v] is None or s.index in shown[v]
    )
    emit(
        "reading",
        {
            "videos": [
                {"title": videos[v].title, "published": videos[v].published_at.date().isoformat()}
                for v in chosen
            ]
        },
    )
    by_platform = {videos[v].platform_id: (videos[v], segments[v]) for v in chosen}
    sponsor_reads = {
        videos[v].platform_id: sponsor_read_texts(segments[v], profiles[v].passages)
        for v in chosen
        if profiles[v]
    }
    # Every kind of written item in the catalogue, not just those read, so the system
    # prompt stays the same across questions and can be cached.
    media = sorted({v.medium for v in videos.values() if v.medium})
    system = answer_system_prompt(creator, media)
    prompt = answer_prompt(question, today or datetime.now(UTC).date())

    # Full mode sends the same corpus with every question, so it goes in `context`,
    # which adapters cache. Hybrid's passages differ per question: caching them would
    # cost more than plain input and never be read back, so they go in the prompt.
    shared = settings.mode == "full"

    def generate(p: str) -> tuple[AnswerDraft, str]:
        raw: list[str] = []
        shown_text = ""

        def on_text(piece: str) -> None:
            nonlocal shown_text
            raw.append(piece)
            text = partial_answer("".join(raw))
            if text != shown_text:
                shown_text = text
                emit("writing", {"text": text})

        result = llm.generate_structured(
            LLMTask.ANSWER,
            system,
            p if shared else f"{corpus}\n\n{p}",
            AnswerDraft,
            context=corpus if shared else None,
            on_text=on_text if on_event else None,
        )
        add_usage(result.usage, result.model)
        return result.value, result.model

    draft, model = generate(prompt)
    checked = check_answer(draft, by_platform, creator.platform, sponsor_reads, creator.own_uploads)
    if checked.problems:
        emit("retrying", {})
        retry = (
            f"{prompt}\n\nYour previous answer had citations that could not be verified:\n"
            + "\n".join(f"- {p}" for p in checked.problems)
            + "\nAnswer again. Copy every quote exactly from the segment you cite."
        )
        draft, model = generate(retry)
        checked = check_answer(
            draft, by_platform, creator.platform, sponsor_reads, creator.own_uploads
        )

    answer_id = None
    if log:
        answer_id = uuid.uuid4().hex
        store.log_answer(
            AnswerLog(
                id=answer_id,
                creator_id=creator.slug,
                asked_at=datetime.now(UTC),
                question=question,
                answer=checked.text,
                covered=checked.coverage,
                changed_mind=checked.changed_mind,
                sources=checked.sources,
                videos_read=chosen,
                parent_id=parent_id,
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
        answer_id=answer_id,
    )


def answerable_videos(
    creator: Creator, store: KnowledgeStore, settings: RetrievalSettings
) -> list[Video]:
    """The videos answers can draw on: all of them, or only profiled ones."""
    return [
        v
        for v in store.list_videos(creator.slug)
        if not settings.require_profiles or store.get_profile(v.id)
    ]


def newer_videos(
    creator: Creator,
    log: AnswerLog,
    store: KnowledgeStore,
    search: SearchIndex,
    settings: RetrievalSettings | None = None,
) -> list[Video]:
    """Videos published after an answer was given that match its question: the
    "new video since you asked" signal. Keyword search only; no model call."""
    usable = answerable_videos(creator, store, settings or RetrievalSettings())
    later = {v.id: v for v in usable if v.published_at > log.asked_at}
    if not later:
        return []
    hits = search.search(SearchQuery(text=log.question, creator_id=creator.slug, limit=100))
    matched = dict.fromkeys(h.video_id for h in hits if h.video_id in later)
    return sorted((later[v] for v in matched), key=lambda v: v.published_at, reverse=True)


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
    entities = store.list_entities(creator.slug) if settings.use_profiles else []
    names = name_variants(plan.names, creator, entities)
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
        if settings.use_profiles:
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
        if settings.use_profiles:
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

    # 3b. Keep brief mentions of the products the question names. The reranker tends
    # to drop a passing line ("the prologue jacket, which is coming back soon") in a
    # video about something else, though it's often the newest thing he said.
    named: list[Pick] = []
    per_video: dict[str, int] = {}
    ignore = [creator.display_name, creator.refer_to_creator_as]
    for i, d in enumerate(candidates):
        if len(named) >= settings.named_total or scores.get(i, 0) >= settings.min_score:
            continue
        vid, seg = by_id[d]
        if per_video.get(vid, 0) < settings.named_per_video and named_in(seg.text, names, ignore):
            per_video[vid] = per_video.get(vid, 0) + 1
            named.append(  # a brief mention: read with its neighbours, not a whole section
                Pick(video_id=vid, segment_index=seg.index, score=fused[d], whole_section=False)
            )
    picks += named  # their scores sit below every reranked pick, so they come last
    trace["kept_by_name"] = len(named)

    # 4. Assemble sections within the word budget.
    shown = expand_to_sections(picks, profiles, segments, settings.context_words)
    return dict(shown.items())
