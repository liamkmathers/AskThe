from askthe.adapters.memory import MemoryKnowledgeStore, MemoryLLMClient, MemorySearchIndex
from askthe.core.extraction import (
    EXTRACTOR_VERSION,
    ClaimDraft,
    ClaimsDraft,
    EntityDraft,
    EntityResolver,
    ProfileDraft,
    SegmentRangeRole,
    normalise,
    quote_location,
)
from askthe.core.interfaces import DocKind, LLMTask, SearchQuery
from askthe.core.models import (
    ClaimKind,
    GlossaryEntry,
    HeldByKind,
    Resolution,
    SegmentRole,
    Use,
    VideoType,
)
from askthe.pipeline.extract import extract_videos
from tests import factories as f

SEGMENTS = [
    "Hello everyone, today we rank t-shirts for value.",
    "The Unilo tee is great for fifteen bucks, I wear it all the time.",
    "This video is sponsored by Clean My Mac and it's great.",
    "People say the Bronson tee is loopwheel, but it's actually not.",
]


def creator():
    return f.creator(glossary=[GlossaryEntry(name="Uniqlo", type="brand", heard_as=["Unilo"])])


def profile_draft(**over):
    fields = dict(
        purpose="Rank t-shirts for value",
        video_type=VideoType.RANKING,
        thesis="Cheap can be good",
        key_takeaways=[],
        outline=[],
        topics=["t-shirts"],
        entities=[
            EntityDraft(name="Unilo", type="brand", heard_as=["Unilo"], identified=True),
            EntityDraft(name="Bronson tee", type="product", identified=True),
        ],
        categories=["t-shirts"],
        non_main_segments=[SegmentRangeRole(first_segment=2, last_segment=2, role="sponsor")],
        corrections=[],
        answers_questions=["What is the best value t-shirt?"],
        uses=[Use.BUYING_DECISION],
        related_videos=[],
    )
    return ProfileDraft(**(fields | over))


def claim_draft(segment, quote, **over):
    fields = dict(
        segment=segment,
        quote=quote,
        kind=ClaimKind.VERDICT,
        entities=[],
        statement="He says something.",
        held_by=HeldByKind.CREATOR,
        certainty="firm",
        he_wears_it=False,
        pros=[],
        cons=[],
        good_for=[],
        bad_for=[],
        attributes=[],
        confidence=0.9,
    )
    return ClaimDraft(**(fields | over))


def setup():
    store, search, llm = MemoryKnowledgeStore(), MemorySearchIndex(), MemoryLLMClient()
    video = f.video("abc")
    store.upsert_video(video)
    store.replace_segments(
        video.id, [f.segment(video.id, i, text=t) for i, t in enumerate(SEGMENTS)]
    )
    return store, search, llm, video


def test_quotes_are_matched_loosely_but_never_invented():
    segs = [f.segment("v", i, text=t) for i, t in enumerate(SEGMENTS)]
    assert quote_location("the unilo TEE is great", 1, segs) == [1]
    assert quote_location("all the time. This video", 1, segs) == [1, 2]
    assert quote_location("the best tee ever made", 1, segs) == []
    assert quote_location("great", 99, segs) == []
    assert normalise("Fjällräven, Kånken!") == "fjallraven kanken"


def test_resolver_uses_glossary_and_keeps_unidentified_names_unresolved():
    resolver = EntityResolver(creator())
    uniqlo = resolver.resolve(EntityDraft(name="Unilo", type="brand", identified=True))
    assert uniqlo.canonical_name == "Uniqlo" and uniqlo.id == "test-creator:e:uniqlo"
    assert resolver.id_for("unilo") == uniqlo.id
    mystery = resolver.entities[resolver.id_for("the Abercrombie something sweatshirt")]
    assert mystery.resolution is Resolution.UNRESOLVED


def test_extract_end_to_end_with_checks():
    store, search, llm, video = setup()
    llm.script(LLMTask.UNDERSTAND, profile_draft())
    llm.script(
        LLMTask.EXTRACT,
        ClaimsDraft(
            claims=[
                claim_draft(
                    1,
                    "The Unilo tee is great for fifteen bucks",
                    entities=["Unilo"],
                    aspect="value",
                    stance="recommend",
                    basis="personal_taste",
                    he_wears_it=True,
                ),
                claim_draft(2, "it's great", entities=["Clean My Mac"]),  # in sponsor read
                claim_draft(
                    3,
                    "People say the Bronson tee is loopwheel",
                    held_by=HeldByKind.OTHERS,
                    entities=["Bronson tee"],
                    kind=ClaimKind.MENTION,
                ),
                claim_draft(1, "the best shirt ever made"),  # not in the transcript
            ]
        ),
    )
    report = extract_videos(creator(), store, search, llm, window_size=8)

    assert not report.failed
    [result] = report.extracted
    assert result.claims == 3 and len(result.rejected) == 1
    claims = store.get_claims_for_video(video.id)
    verdict, sponsor, reported = claims
    assert verdict.he_wears_it and verdict.entity_ids == ["test-creator:e:uniqlo"]
    assert sponsor.sponsored and sponsor.kind is ClaimKind.SPONSORSHIP
    assert not reported.is_creators_view
    assert all(c.extractor_version == EXTRACTOR_VERSION for c in claims)

    profile = store.get_profile(video.id)
    assert profile.video_type is VideoType.RANKING
    roles = [s.role for s in store.get_segments(video.id)]
    assert roles == [SegmentRole.MAIN, SegmentRole.MAIN, SegmentRole.SPONSOR, SegmentRole.MAIN]
    assert store.get_entity("test-creator:e:uniqlo").aliases == ["Unilo"]

    # The whole transcript is sent as the shared, cacheable context on every call.
    assert all("[3] People say" in context for _, _, _, context in llm.calls)

    hits = search.search(
        SearchQuery(
            text="best value t-shirt", creator_id="test-creator", kinds=[DocKind.PROFILE_QUESTION]
        )
    )
    assert hits and hits[0].video_id == video.id

    # Re-running skips videos already done by this extractor version.
    again = extract_videos(creator(), store, search, llm)
    assert again.skipped == [video.id] and not again.extracted


def test_one_failing_video_does_not_stop_the_rest():
    store, search, llm, video = setup()
    report = extract_videos(creator(), store, search, llm)  # nothing scripted: LLM fails
    assert list(report.failed) == [video.id]
    assert store.get_profile(video.id) is None
