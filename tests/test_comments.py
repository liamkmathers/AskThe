"""Comments: fetching into the raw archive, and picking fan questions out of them."""

from datetime import UTC, datetime

import pytest

from askthe.adapters.files import FileRawArchive
from askthe.adapters.memory import MemoryCommentSource, MemoryRawArchive
from askthe.adapters.youtube import comment_from_info
from askthe.core.models import Comment, RawComments
from askthe.core.questions import is_question, question_candidates
from askthe.pipeline.comments import fetch_comments
from tests import factories as f

ARCHIVES = {
    "memory": lambda tmp: MemoryRawArchive(),
    "files": lambda tmp: FileRawArchive(tmp),
}


@pytest.fixture(params=list(ARCHIVES))
def archive(request, tmp_path):
    return ARCHIVES[request.param](tmp_path)


def comment(cid: str, text: str, likes: int = 0, **over) -> Comment:
    return Comment(id=cid, text=text, like_count=likes, **over)


def batch(platform_id: str, *comments: Comment) -> RawComments:
    return RawComments(
        creator_slug=f.CREATOR,
        platform_id=platform_id,
        comments=list(comments),
        fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
        source="memory",
    )


def test_archive_keeps_comments_apart_from_videos_and_never_overwrites(archive):
    archive.save(f.raw_video("abc"))
    assert not archive.has_comments(f.CREATOR, "abc")
    archive.save_comments(batch("abc", comment("c1", "Nice")))
    assert archive.has_comments(f.CREATOR, "abc")
    assert archive.load_comments(f.CREATOR, "abc").comments[0].id == "c1"
    assert archive.list_comment_ids(f.CREATOR) == ["abc"]
    assert archive.list_ids(f.CREATOR) == ["abc"]  # comments are not videos
    with pytest.raises(FileExistsError):
        archive.save_comments(batch("abc"))
    with pytest.raises(LookupError):
        archive.load_comments(f.CREATOR, "missing")


def test_fetch_comments_skips_done_videos_and_keeps_going_after_a_failure():
    source, archive = MemoryCommentSource(), MemoryRawArchive()
    source.add("a", comment("c1", "low", 1), comment("c2", "high", 9), comment("c3", "mid", 5))
    source.fail.add("b")
    archive.save_comments(batch("c"))
    report = fetch_comments(
        f.creator(), ["a", "b", "c"], source, archive, source_name="memory", per_video=2
    )
    assert report.fetched == ["a"] and report.skipped == ["c"] and list(report.failed) == ["b"]
    assert [c.id for c in archive.load_comments(f.CREATOR, "a").comments] == ["c2", "c3"]


def test_fetch_comments_stops_after_consecutive_failures():
    source = MemoryCommentSource()
    source.fail.update({"a", "b", "c"})
    report = fetch_comments(
        f.creator(),
        ["a", "b", "c"],
        source,
        MemoryRawArchive(),
        "memory",
        max_consecutive_failures=2,
    )
    assert report.stopped_early and list(report.failed) == ["a", "b"]


def test_yt_dlp_comments_drop_the_author():
    c = comment_from_info(
        {
            "id": "Ugx1",
            "text": "Thoughts on Iron Rangers?",
            "like_count": 12,
            "author": "Someone",
            "author_is_uploader": False,
            "parent": "root",
            "timestamp": 1_700_000_000,
        }
    )
    assert c.like_count == 12 and not c.is_reply and not c.by_creator
    assert "Someone" not in c.model_dump_json()


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Would these work for wide feet?", True),
        ("Thoughts on the Red Wing Iron Ranger", True),
        ("Which one would you pick for winter", True),
        ("Great video, love the channel", False),
        ("Nice", False),
    ],
)
def test_is_question(text, expected):
    assert is_question(text) is expected


def test_candidates_are_viewer_questions_most_liked_first_without_duplicates():
    found = question_candidates(
        [
            batch(
                "abc",
                comment("c1", "Great video, love the channel as always", 100),
                comment("c2", "Is the Uniqlo tee still good after washing?", 5),
                comment("c3", "Can you review Arc'teryx Beta jackets please?", 20),
                comment("c4", "Is the Uniqlo tee still good after washing?!", 3),
                comment("c5", "What boots are you wearing in this one?", 50, by_creator=True),
                comment("c6", "Where to buy? https://example.com/x", 9),
                comment("c7", "Why?", 40),
            )
        ],
        titles={"abc": "T-shirts ranked"},
        url_for={"abc": "https://www.youtube.com/watch?v=abc"},
    )
    assert [(q.id, q.kind) for q in found] == [("c3", "request"), ("c2", "question")]
    assert found[1].url == "https://www.youtube.com/watch?v=abc&lc=c2"
    assert found[1].video_title == "T-shirts ranked"


def test_limit_counts_only_videos_not_yet_done(tmp_path):
    from typer.testing import CliRunner

    from askthe.cli import app

    (tmp_path / "creators").mkdir()
    (tmp_path / "creators" / f"{f.CREATOR}.yaml").write_text(f.creator().model_dump_json())
    ports = {
        "catalog": "memory",
        "transcripts": "memory",
        "comments": "memory",
        "raw_archive": "files",
        "profiles": "files",
        "store": "memory",
        "search": "memory",
        "embedder": "memory",
        "vectors": "memory",
        "llm": "memory",
    }
    (tmp_path / "askthe.toml").write_text(
        'data_dir = "data"\ncreators_dir = "creators"\n'
        + "".join(f'[adapters.{p}]\nuse = "{u}"\n' for p, u in ports.items())
    )
    FileRawArchive(tmp_path / "data").save_comments(batch("a"))
    result = CliRunner().invoke(
        app,
        [
            "comments",
            f.CREATOR,
            "-v",
            "a",
            "-v",
            "b",
            "-v",
            "c",
            "--limit",
            "1",
            "--delay",
            "0",
            "--config",
            str(tmp_path / "askthe.toml"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert FileRawArchive(tmp_path / "data").list_comment_ids(f.CREATOR) == ["a", "b"]
