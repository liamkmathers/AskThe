"""The creator bio: made from their own words, every item quoted and verified."""

from askthe.core.bio import BioDraft, CitationDraft, ItemDraft
from askthe.core.interfaces import LLMTask
from askthe.core.models import VideoProfile, VideoType
from askthe.core.profiling import PROFILER_VERSION
from askthe.pipeline.bio import make_bio
from tests import factories as f
from tests.test_retrieval import build


def profile(video_id):
    return VideoProfile(
        video_id=video_id,
        purpose="Winter boots",
        video_type=VideoType.REVIEW,
        thesis="t",
        profiler_version=PROFILER_VERSION,
        model="m",
    )


def item(title, text, quote, video="boots"):
    return ItemDraft(title=title, text=text, citations=[CitationDraft(video=video, quote=quote)])


def test_bio_keeps_verified_professional_items_only():
    store, search, llm, _, _ = build()  # "boots" and "denim"; only boots gets a profile
    store.save_profile(profile(f.video("boots").id))
    seen = {}

    def write(context, prompt):
        seen["context"] = context
        return BioDraft(
            summary="Reviews boots in depth.",
            journey=[
                item("Winter boots", "Started with boots.", "kept my feet warm in the snow"),
                item("Made up", "Never said.", "words he never said"),
                item("Moved in", "His girlfriend moved in.", "Welcome back"),
            ],
            ventures=[item("Denim", "Raw denim talk.", "indigo fades", video="denim")],
        )

    llm.script(LLMTask.BIO, write)
    report = make_bio(f.creator(), store, search, llm)
    assert [i.title for i in report.bio.journey] == ["Winter boots"]
    assert report.bio.journey[0].citations[0].video_id == "boots"
    assert report.bio.ventures == []  # denim isn't profiled, so it can't be cited
    assert len(report.dropped) == 3
    assert "[boots]" in seen["context"] and "[denim]" not in seen["context"]
