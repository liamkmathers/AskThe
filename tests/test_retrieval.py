from askthe.adapters.memory import (
    MemoryEmbedder,
    MemoryKnowledgeStore,
    MemoryLLMClient,
    MemorySearchIndex,
    MemoryVectorIndex,
)
from askthe.core.answering import AnswerDraft, CitationDraft, render_video
from askthe.core.interfaces import EmbeddingError, LLMTask
from askthe.core.models import Coverage, GlossaryEntry, OutlineSection, VideoProfile, VideoType
from askthe.core.profiling import PROFILER_VERSION
from askthe.core.retrieval import (
    PassageScore,
    Pick,
    QueryPlan,
    RerankDraft,
    expand_to_sections,
    name_variants,
    reciprocal_rank_fusion,
)
from askthe.pipeline.ask import RetrievalSettings, ask
from askthe.pipeline.index import index_videos
from tests import factories as f


def test_rank_fusion_rewards_agreement_between_lists():
    fused = reciprocal_rank_fusion([["a", "b", "c"], ["b", "a"], ["b"]])
    assert max(fused, key=fused.get) == "b"
    assert fused["c"] < fused["a"]


def test_name_variants_include_glossary_misspellings():
    c = f.creator(glossary=[GlossaryEntry(name="Uniqlo", type="brand", heard_as=["Unilo"])])
    assert name_variants(["uniqlo"], c, []) == ["uniqlo", "Uniqlo", "Unilo"]
    assert name_variants(["Bronson"], c, []) == ["Bronson"]


def test_name_variants_match_aliases_but_not_short_fragments():
    c = f.creator(
        glossary=[
            GlossaryEntry(
                name="Prologue Denim Jacket", type="product", heard_as=["Iron Snail denim jacket"]
            )
        ]
    )
    found = name_variants(["Iron Snail denim jackets"], c, [])
    assert "Prologue Denim Jacket" in found
    msb = f.entity("Merz b. Schwanen", aliases=["B", "MSB"])
    assert name_variants(["Bronson"], c, [msb]) == ["Bronson"]  # "b" is too short to match
    assert "Merz b. Schwanen" in name_variants(["MSB"], c, [msb])  # exact matches still do


def profile(video_id, outline):
    return VideoProfile(
        video_id=video_id,
        purpose="p",
        video_type=VideoType.REVIEW,
        thesis="t",
        outline=outline,
        profiler_version=PROFILER_VERSION,
        model="m",
    )


def test_picks_expand_to_short_sections_or_neighbours_within_budget():
    vid = "test-creator:v"
    segs = {vid: [f.segment(vid, i, text="word " * 100) for i in range(20)]}
    prof = {
        vid: profile(
            vid,
            [
                OutlineSection(title="short", first_segment=2, last_segment=4),
                OutlineSection(title="long", first_segment=5, last_segment=19),
            ],
        )
    }
    shown = expand_to_sections(
        [Pick(vid, 3, 3.0), Pick(vid, 10, 2.0)], prof, segs, budget_words=10_000
    )
    assert shown == {vid: [2, 3, 4, 9, 10, 11]}
    # With a tight budget only the best pick fits.
    assert expand_to_sections(
        [Pick(vid, 3, 3.0), Pick(vid, 10, 2.0)], prof, segs, budget_words=300
    ) == {vid: [2, 3, 4]}


def test_partial_transcripts_mark_what_is_not_shown():
    video = f.video("abc")
    segs = [f.segment(video.id, i, text=f"text {i}") for i in range(6)]
    rendered = render_video(video, None, segs, only=[2, 3])
    assert "[... segments 0-1 not shown ...]" in rendered
    assert "[abc:2] text 2" in rendered and "[abc:3] text 3" in rendered
    assert "[... segments 4-5 not shown ...]" in rendered and "text 5" not in rendered


SEGMENTS = {
    "boots": [
        "Welcome back. Today is all about winter boots.",
        "These Red Wing boots kept my feet warm in the snow, I wear them every winter.",
        "This video is sponsored by a hair dryer, link below.",
    ],
    "denim": [
        "Raw denim from Japan is my favourite, the indigo fades beautifully.",
        "Wrangler beats Levi's on value.",
    ],
}


def build():
    store, search, llm = MemoryKnowledgeStore(), MemorySearchIndex(), MemoryLLMClient()
    vectors, embedder = MemoryVectorIndex(), MemoryEmbedder()
    for pid, texts in SEGMENTS.items():
        video = f.video(pid, title=f"All about {pid}")
        store.upsert_video(video)
        store.replace_segments(
            video.id, [f.segment(video.id, i, text=t) for i, t in enumerate(texts)]
        )
    index_videos(f.creator(), store, search, vectors, embedder)
    return store, search, llm, vectors, embedder


def answer(quote_video, segment, quote):
    return AnswerDraft(
        answer="He keeps warm in Red Wings [1].",
        coverage=Coverage.FULL,
        citations=[CitationDraft(n=1, video=quote_video, segment=segment, quote=quote)],
    )


def test_hybrid_reads_only_the_relevant_sections():
    store, search, llm, vectors, embedder = build()
    llm.script(
        LLMTask.PLAN, QueryPlan(queries=["warm winter boots snow"], names=["Red Wing"], broad=False)
    )

    def rerank(context, prompt):
        # The boots passage about warmth is the one that answers the question.
        n = prompt.split("<passage n=")
        best = next(i for i, part in enumerate(n[1:]) if "kept my feet warm" in part)
        return RerankDraft(scores=[PassageScore(n=best, score=3)])

    llm.script(LLMTask.RERANK, rerank)
    llm.script(LLMTask.ANSWER, answer("boots", 1, "kept my feet warm in the snow"))

    result = ask(
        f.creator(),
        "Which boots keep you warm in winter?",
        store,
        search,
        llm,
        vectors=vectors,
        embedder=embedder,
        settings=RetrievalSettings(context_words=1000),
    )

    assert result.videos_read == ["test-creator:boots"]
    assert [s.quote for s in result.answer.sources] == ["kept my feet warm in the snow"]
    _, _, prompt, context = [c for c in llm.calls if c[0] is LLMTask.ANSWER][0]
    assert "kept my feet warm" in prompt and "Raw denim" not in prompt
    assert context is None  # passages differ per question: sent as input, not cached
    assert result.trace["queries"][0] == "Which boots keep you warm in winter?"
    assert result.trace["kept"] == 1 and not result.trace["warnings"]


def test_hybrid_falls_back_to_keywords_when_embeddings_fail():
    store, search, llm, vectors, _ = build()

    class Down:
        name = "down"

        def embed(self, texts):
            raise EmbeddingError("no API key")

    llm.script(LLMTask.PLAN, QueryPlan(queries=["raw denim"], names=[], broad=False))
    llm.script(LLMTask.RERANK, lambda c, p: RerankDraft(scores=[PassageScore(n=0, score=3)]))
    llm.script(
        LLMTask.ANSWER, AnswerDraft(answer="Not covered.", coverage=Coverage.NONE, citations=[])
    )
    result = ask(f.creator(), "raw denim?", store, search, llm, vectors=vectors, embedder=Down())
    assert "keyword only" in result.trace["warnings"][0]
    assert result.answer.coverage is Coverage.NONE


def test_named_in_matches_whole_names_but_not_short_or_ignored_ones():
    from askthe.core.retrieval import named_in

    text = "the prologue jacket which is coming back soon"
    assert named_in(text, ["Prologue jacket"])
    assert not named_in(text, ["pro", "jack"])  # too short, or not a whole word
    assert not named_in("The Iron Snail says hi", ["The Iron Snail"], ignore=["The Iron Snail"])


def test_hybrid_keeps_a_passage_naming_the_product_even_if_reranked_low():
    store, search, llm, vectors, embedder = build()
    llm.script(LLMTask.PLAN, QueryPlan(queries=["winter boots"], names=["Red Wing"], broad=False))
    llm.script(LLMTask.RERANK, lambda c, p: RerankDraft(scores=[]))  # keeps nothing
    llm.script(LLMTask.ANSWER, answer("boots", 1, "kept my feet warm in the snow"))
    result = ask(
        f.creator(), "Red Wings in winter?", store, search, llm, vectors=vectors, embedder=embedder
    )
    assert result.trace["kept"] == 0 and result.trace["kept_by_name"] == 1
    assert result.videos_read == ["test-creator:boots"]
    assert [s.quote for s in result.answer.sources] == ["kept my feet warm in the snow"]
