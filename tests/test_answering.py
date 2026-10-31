from datetime import UTC, date, datetime

from askthe.adapters.memory import MemoryKnowledgeStore, MemoryLLMClient, MemorySearchIndex
from askthe.core.answering import (
    UNMARKED,
    AnswerDraft,
    CitationDraft,
    check_answer,
    mark_passages,
    render_video,
    select_videos,
)
from askthe.core.interfaces import LLMTask
from askthe.core.models import Coverage, GlossaryEntry, Passage, PassageRole, Use, VideoType
from askthe.core.profiling import (
    PROFILER_VERSION,
    EntityDraft,
    EntityResolver,
    PassageDraft,
    ProfileDraft,
    SectionDraft,
)
from askthe.pipeline.ask import RetrievalSettings, ask
from askthe.pipeline.understand import understand_videos
from tests import factories as f

SEGMENTS = [
    "Hello everyone, today we rank t-shirts for value.",
    "The Unilo tee is great for fifteen bucks, I wear it all the time. "
    "This video is sponsored by Clean My Mac and it's great, link below. Anyway, back to shirts.",
    "People say the Bronson tee is loopwheel, but it's actually not.",
]


def creator():
    return f.creator(glossary=[GlossaryEntry(name="Uniqlo", type="brand", heard_as=["Unilo"])])


def segments(video_id="test-creator:abc"):
    return [f.segment(video_id, i, text=t) for i, t in enumerate(SEGMENTS)]


SPONSOR = Passage(
    role=PassageRole.SPONSOR,
    first_segment=1,
    starts_with="This video is sponsored by",
    last_segment=1,
    ends_with="link below",
    note="Clean My Mac",
)


def profile_draft():
    return ProfileDraft(
        purpose="Rank t-shirts for value",
        video_type=VideoType.RANKING,
        thesis="Cheap can be good",
        key_takeaways=[],
        topics=["t-shirts"],
        categories=["t-shirts"],
        corrections=[],
        sections=[
            SectionDraft(
                title="Cheap tees", summary="Uniqlo and others", first_segment=0, last_segment=2
            )
        ],
        entities=[EntityDraft(name="Unilo", type="brand", heard_as=["Unilo"], identified=True)],
        passages=[
            PassageDraft(
                role="sponsor",
                first_segment=1,
                starts_with="This video is sponsored by",
                last_segment=1,
                ends_with="link below",
                note="Clean My Mac",
            )
        ],
        answers_questions=["What is the best value t-shirt?"],
        uses=[Use.BUYING_DECISION],
        related_videos=[],
    )


def test_sponsor_reads_are_marked_mid_segment_without_touching_the_rest():
    texts, unlocated = mark_passages(segments(), [SPONSOR])
    assert not unlocated
    assert texts[1].startswith("The Unilo tee is great")  # his own opinion stays unmarked
    assert "«SPONSOR: Clean My Mac» This video is sponsored" in texts[1]
    assert "link below «END SPONSOR». Anyway" in texts[1]


def test_passages_that_cannot_be_located_are_reported_not_guessed():
    lost = SPONSOR.model_copy(update={"starts_with": "words that are not there"})
    texts, unlocated = mark_passages(segments(), [lost])
    assert unlocated == [lost] and "«" not in texts[1]
    video = f.video("abc")
    rendered = render_video(
        video,
        f_profile(video.id, passages=[lost]),
        segments(),
    )
    assert "exact bounds are unknown" in rendered and "[abc:2] People say" in rendered


def f_profile(video_id, **over):
    from askthe.core.models import VideoProfile

    fields = dict(
        video_id=video_id,
        purpose="p",
        video_type=VideoType.RANKING,
        thesis="t",
        profiler_version=PROFILER_VERSION,
        model="m",
    )
    return VideoProfile(**(fields | over))


def test_everything_is_read_when_it_fits_else_the_most_relevant():
    words = {"a": 100, "b": 100, "c": 100}
    assert select_videos(words, {}, budget_words=300) == ["a", "b", "c"]
    assert select_videos(words, {"c": 9.0, "a": 5.0, "b": 1.0}, budget_words=200) == ["c", "a"]


def test_citations_are_verified_and_failures_removed():
    video = f.video("abc")
    draft = AnswerDraft(
        answer="He loves the Uniqlo tee [1] and calls it the best ever [2].",
        coverage=Coverage.FULL,
        citations=[
            CitationDraft(n=1, video="abc", segment=1, quote="The Unilo tee is great"),
            CitationDraft(n=2, video="abc", segment=1, quote="the best shirt ever made"),
        ],
    )
    checked = check_answer(draft, {"abc": (video, segments())}, "youtube")
    assert [s.n for s in checked.sources] == [1]
    assert checked.sources[0].url == "https://www.youtube.com/watch?v=abc"
    assert "[2]" not in checked.text and len(checked.problems) == 1


def setup():
    store, search, llm = MemoryKnowledgeStore(), MemorySearchIndex(), MemoryLLMClient()
    video = f.video("abc")
    store.upsert_video(video)
    store.replace_segments(video.id, segments(video.id))
    return store, search, llm, video


def test_understand_profiles_and_indexes_and_skips_on_rerun():
    store, search, llm, video = setup()
    llm.script(LLMTask.UNDERSTAND, profile_draft())
    report = understand_videos(creator(), store, llm)
    assert report.profiled == [video.id] and not report.failed
    profile = store.get_profile(video.id)
    assert profile.passages[0].role is PassageRole.SPONSOR
    assert profile.outline[0].summary == "Uniqlo and others"
    assert store.get_entity("test-creator:e:uniqlo").aliases == ["Unilo"]
    again = understand_videos(creator(), store, llm)
    assert again.skipped == [video.id]


def test_ask_reads_marked_transcripts_and_retries_bad_citations():
    store, search, llm, video = setup()
    llm.script(LLMTask.UNDERSTAND, profile_draft())
    understand_videos(creator(), store, llm)

    bad = AnswerDraft(
        answer="Best ever [1].",
        coverage=Coverage.FULL,
        citations=[CitationDraft(n=1, video="abc", segment=1, quote="best shirt ever made")],
    )
    good = AnswerDraft(
        answer="He rates the Uniqlo tee for value and wears it [1].",
        coverage=Coverage.FULL,
        citations=[CitationDraft(n=1, video="abc", segment=1, quote="I wear it all the time")],
    )
    llm.script(LLMTask.ANSWER, bad, good)

    result = ask(
        creator(),
        "best value t-shirt?",
        store,
        search,
        llm,
        settings=RetrievalSettings(mode="full"),
        today=date(2026, 10, 29),
    )
    assert result.videos_read == [video.id]
    assert [s.quote for s in result.answer.sources] == ["I wear it all the time"]
    assert not result.answer.problems

    first_call, retry_call = [c for c in llm.calls if c[0] is LLMTask.ANSWER]
    context = first_call[3]
    assert "«SPONSOR: Clean My Mac»" in context and "[abc:1] The Unilo tee" in context
    assert "Today is 2026-10-29" in first_call[2]
    assert "could not be verified" in retry_call[2]
    [log] = store.list_answers("test-creator")
    assert log.cited_segment_ids == ["test-creator:abc:s0001"]


def test_resolver_uses_glossary():
    resolver = EntityResolver(creator())
    entity = resolver.resolve(EntityDraft(name="Unilo", type="brand", identified=True))
    assert entity.canonical_name == "Uniqlo"


def test_published_dates_reach_the_model():
    video = f.video("abc", published_at=datetime(2024, 3, 9, tzinfo=UTC))
    assert "Published: 2024-03-09" in render_video(video, None, segments())


def test_descriptions_are_shown_and_citable_with_links_collapsed():
    from askthe.core.answering import DESCRIPTION, clean_description

    video = f.video(
        "abc",
        description="Use code SNAIL10 https://example.com/x?utm=1\n\n\n\nI also love the Muji tee.",
    )
    rendered = render_video(video, None, segments(video.id))
    assert "[abc:-1] Use code SNAIL10 <link>" in rendered
    assert clean_description(video.description).count("\n") == 2
    draft = AnswerDraft(
        answer="He loves the Muji tee [1], and the code [2], and more [3].",
        coverage=Coverage.FULL,
        citations=[
            CitationDraft(n=1, video="abc", segment=DESCRIPTION, quote="I also love the Muji tee"),
            CitationDraft(n=2, video="abc", segment=DESCRIPTION, quote="SNAIL10 link"),
            CitationDraft(n=3, video="abc", segment=DESCRIPTION, quote="not in the description"),
        ],
    )
    checked = check_answer(draft, {"abc": (video, segments(video.id))}, "youtube")
    assert [(s.n, s.in_description, s.segment_ids) for s in checked.sources] == [
        (1, True, []),
        (2, True, []),
    ]
    assert len(checked.problems) == 1


def test_an_empty_corpus_says_nothing_matched():
    from askthe.core.answering import render_corpus

    assert "Nothing in his videos matched" in render_corpus([])


def test_verified_quotes_keep_the_words_around_them():
    from askthe.core.answering import quote_context

    text = " ".join(f"w{i}" for i in range(100)) + " the storm welt is invaluable to me " + "end"
    before, after = quote_context("storm welt is invaluable", text, words=3)
    assert before == "… w98 w99 the" and after == "to me end"
    assert quote_context("not there", text) == ("", "")

    video = f.video("abc")
    segs = [
        f.segment(video.id, 0, "Leading in. The Unilo tee"),
        f.segment(video.id, 1, "is great for fifteen bucks. Moving on."),
    ]
    draft = AnswerDraft(
        answer="He rates it [1].",
        coverage=Coverage.FULL,
        citations=[CitationDraft(n=1, video="abc", segment=1, quote="great for fifteen bucks")],
    )
    source = check_answer(draft, {"abc": (video, segs)}, "youtube").sources[0]
    assert source.context_before == "Leading in. The Unilo tee is"  # runs into the segment before
    assert source.context_after == ". Moving on."  # punctuation after the quote is kept


def test_a_video_without_a_profile_is_flagged_as_unmarked():
    video = f.video("boots")
    segments = [f.segment(video.id, 0, text="This video is brought to you by a hair dryer.")]
    assert UNMARKED in render_video(video, None, segments)


def test_descriptions_by_someone_else_are_neither_shown_nor_quotable():
    video = f.video("talk", description="Keynote by our guest at the 2024 summit.")
    segments = [f.segment(video.id, 0, text="Quantum will change discovery.")]
    assert "Keynote by our guest" in render_video(video, None, segments)
    assert "Keynote by our guest" not in render_video(video, None, segments, description=False)

    draft = AnswerDraft(
        answer="He calls it a keynote [1].",
        coverage=Coverage.FULL,
        citations=[CitationDraft(n=1, video="talk", segment=-1, quote="Keynote by our guest")],
    )
    videos = {"talk": (video, segments)}
    assert check_answer(draft, videos, "youtube").sources
    assert not check_answer(draft, videos, "youtube", descriptions=False).sources
