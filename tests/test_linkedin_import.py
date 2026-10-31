"""Importing posts and articles from a LinkedIn data export (D29).

The fixture under tests/fixtures/linkedin_export/ is synthetic: no real person's data.
"""

import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from askthe.adapters.files import FileRawArchive
from askthe.adapters.linkedin_export import LinkedInExportSource, parse_date
from askthe.adapters.memory import MemoryExportSource, MemoryRawArchive
from askthe.cli import app
from askthe.core.answering import (
    AnswerDraft,
    CitationDraft,
    answer_system_prompt,
    check_answer,
    render_video,
)
from askthe.core.chunking import chunk_header
from askthe.core.interfaces import ExportContents, ExportSource
from askthe.core.models import Coverage
from askthe.core.segmenting import segment_text, video_from_raw
from askthe.pipeline.imports import import_export
from tests import factories as f

EXPORT = Path(__file__).parent / "fixtures" / "linkedin_export"
POST_URL = "https://www.linkedin.com/feed/update/urn%3Ali%3Ashare%3A7190000000000000001/"
ARTICLE_URL = "https://www.linkedin.com/pulse/why-we-measure-test-creator-abc12"


def read(path: Path = EXPORT, **kw) -> ExportContents:
    return LinkedInExportSource().read_export(f.creator(), path, **kw)


def by_id(contents: ExportContents) -> dict:
    return {i.meta.platform_id: i for i in contents.items}


def test_the_reader_implements_the_port():
    assert isinstance(LinkedInExportSource(), ExportSource)
    assert isinstance(MemoryExportSource(), ExportSource)


def test_posts_are_imported_with_their_dates_urls_and_text():
    items = by_id(read())
    post = items["linkedin-share-7190000000000000001"]
    assert post.creator_slug == f.CREATOR and post.source == "linkedin-export"
    assert post.meta.medium == "LinkedIn post"
    assert post.meta.url == POST_URL
    assert post.meta.published_at == datetime(2024, 5, 2, 8, 15, tzinfo=UTC)
    assert post.meta.title == "Faster computers are not enough."
    # LinkedIn's hashtag markup is made plain; CSV-escaped quotes come through.
    assert "the #future of computing" in post.transcript.text
    assert '"measure twice"' in post.transcript.text
    assert post.transcript.kind.value == "manual" and post.transcript.language == "en"


def test_reposts_without_commentary_are_skipped_and_with_commentary_keep_only_his_words():
    contents = read()
    items = by_id(contents)
    assert "linkedin-activity-7200000000000000002" not in items
    reasons = list(contents.skipped.values())
    assert "repost with no commentary of his own" in reasons
    repost = items["linkedin-share-7210000000000000003"]
    assert repost.transcript.text == (
        "Proud of this team. Measuring before claiming is the only way to know."
    )
    # Image-only posts have no words; connections-only posts were never public.
    assert any(r.startswith("no text") for r in reasons)
    assert any(r.startswith("visible to connections only") for r in reasons)
    assert "linkedin-share-7230000000000000005" not in items


def test_articles_are_imported_and_drafts_left_out():
    contents = read()
    article = by_id(contents)["linkedin-article-why-we-measure-test-creator-abc12"]
    assert article.meta.medium == "LinkedIn article" and article.meta.url == ARTICLE_URL
    assert article.meta.title == "Why we measure"
    assert article.meta.published_at == datetime(2024, 3, 5, 9, 0, tzinfo=UTC)
    text = article.transcript.text
    assert text.startswith("Every claim of progress should come with a measurement.")
    assert "an opinion & a hope" in text and "Energy per result" in text
    assert "Created on" not in text and "Published on" not in text and "Why we measure" not in text
    assert any("draft" in why for why in contents.skipped.values())
    assert len(contents.items) == 3  # two posts and one article


def test_comments_are_left_out_unless_asked_for():
    assert not [i for i in read().items if i.meta.medium == "LinkedIn comment"]
    comments = [i for i in read(include_comments=True).items if i.meta.medium == "LinkedIn comment"]
    assert len(comments) == 1
    comment = comments[0]
    assert comment.meta.platform_id == "linkedin-comment-7211111111111111111"
    assert comment.transcript.text.startswith("Agreed: the benchmark matters")
    assert comment.meta.url.startswith("https://www.linkedin.com/feed/update/")


def test_a_zipped_export_reads_the_same_as_its_folder(tmp_path):
    archive = tmp_path / "Basic_LinkedInDataExport.zip"
    with zipfile.ZipFile(archive, "w") as z:
        for path in EXPORT.rglob("*"):
            if path.is_file():
                z.write(path, path.relative_to(EXPORT).as_posix())
        z.writestr("__MACOSX/._Shares.csv", "junk")
    zipped, folder = read(archive), read()
    assert sorted(by_id(zipped)) == sorted(by_id(folder))
    assert by_id(zipped)["linkedin-share-7190000000000000001"].transcript == (
        by_id(folder)["linkedin-share-7190000000000000001"].transcript
    )


def test_a_missing_articles_folder_and_renamed_columns_are_tolerated(tmp_path):
    export = tmp_path / "export"
    export.mkdir()
    # An older layout: notes above the header, other column names, no Articles folder.
    (export / "shares.csv").write_text(
        "Notes:\n"
        '"This file contains your posts."\n'
        "\n"
        "Created Date,Post Link,Commentary,Shared URL\n"
        '05/02/2023 08:15:00,"https://www.linkedin.com/posts/test-creator_quantum-activity-'
        '7060000000000000001-AbCd",Quantum needs patience.,\n',
        encoding="utf-8-sig",
    )
    contents = read(export)
    (post,) = contents.items
    assert post.meta.platform_id == "linkedin-activity-7060000000000000001"
    assert post.meta.published_at == datetime(2023, 5, 2, 8, 15, tzinfo=UTC)
    assert post.transcript.text == "Quantum needs patience."
    # An export with none of the files: nothing to import, and no error.
    empty = tmp_path / "empty"
    empty.mkdir()
    assert read(empty, include_comments=True) == ExportContents()


def test_dates_in_the_formats_linkedin_has_used():
    assert parse_date("2024-05-02 08:15:00") == datetime(2024, 5, 2, 8, 15, tzinfo=UTC)
    assert parse_date("2024-05-02 08:15:00 UTC") == datetime(2024, 5, 2, 8, 15, tzinfo=UTC)
    assert parse_date("2024-05-02T08:15:00Z") == datetime(2024, 5, 2, 8, 15, tzinfo=UTC)
    assert parse_date("May 2, 2024") == datetime(2024, 5, 2, tzinfo=UTC)
    assert parse_date("sometime") is None


def test_reimporting_the_same_export_is_idempotent(tmp_path):
    archive = FileRawArchive(tmp_path / "data")
    first = import_export(f.creator(), EXPORT, LinkedInExportSource(), archive)
    assert len(first.imported) == 3 and not first.already
    saved = {p: p.read_text() for p in (tmp_path / "data").rglob("*.json")}
    second = import_export(f.creator(), EXPORT, LinkedInExportSource(), archive)
    assert not second.imported and sorted(second.already) == sorted(first.imported)
    assert {p: p.read_text() for p in (tmp_path / "data").rglob("*.json")} == saved
    # A later export with comments adds only what's new.
    third = import_export(
        f.creator(), EXPORT, LinkedInExportSource(), archive, include_comments=True
    )
    assert third.imported == ["linkedin-comment-7211111111111111111"]


def test_import_uses_the_port_so_a_fake_works():
    source, archive = MemoryExportSource(), MemoryRawArchive()
    item = f.raw_video("linkedin-share-1")
    source.exports["export.zip"] = ExportContents(items=[item], skipped={"row 2": "repost"})
    report = import_export(f.creator(), Path("export.zip"), source, archive)
    assert report.imported == ["linkedin-share-1"] and report.skipped == {"row 2": "repost"}
    assert archive.has(f.CREATOR, "linkedin-share-1")


def post_video_and_segments():
    raw = by_id(read())["linkedin-share-7190000000000000001"]
    video = video_from_raw(raw)
    return video, segment_text(video.id, raw.transcript.text)


def test_citations_of_a_post_link_to_the_post_not_youtube():
    video, segments = post_video_and_segments()
    assert video.medium == "LinkedIn post" and video.url == POST_URL
    draft = AnswerDraft(
        answer="He says faster computers are not enough [1].",
        coverage=Coverage.FULL,
        citations=[
            CitationDraft(
                n=1, video=video.platform_id, segment=0, quote="Faster computers are not enough."
            )
        ],
    )
    checked = check_answer(draft, {video.platform_id: (video, segments)}, "youtube")
    assert not checked.problems
    (source,) = checked.sources
    assert source.url == POST_URL and source.medium == "LinkedIn post"
    assert "youtube" not in source.url


def test_posts_are_shown_and_named_as_posts():
    video, segments = post_video_and_segments()
    shown = render_video(video, None, segments, description=False)
    assert "Medium: LinkedIn post (written by him, not a video)" in shown
    assert "\nText:\n" in shown
    assert chunk_header(video, None, 0).startswith("LinkedIn post: Faster computers")
    creator = f.creator()
    assert "Written items" not in answer_system_prompt(creator)  # unchanged for videos only
    prompt = answer_system_prompt(creator, ["LinkedIn post"])
    assert "Written items" in prompt and "in a LinkedIn post" in prompt


def test_import_linkedin_command(tmp_path):
    (tmp_path / "creators").mkdir()
    (tmp_path / "creators" / f"{f.CREATOR}.yaml").write_text(f.creator().model_dump_json())
    ports = dict.fromkeys(
        "catalog transcripts comments profiles store search embedder vectors llm".split(),
        "memory",
    ) | {"raw_archive": "files"}
    (tmp_path / "askthe.toml").write_text(
        'data_dir = "data"\ncreators_dir = "creators"\n'
        + "".join(f'[adapters.{p}]\nuse = "{u}"\n' for p, u in ports.items())
    )
    export = tmp_path / "export"
    shutil.copytree(EXPORT, export)
    config = ["--config", str(tmp_path / "askthe.toml")]
    result = CliRunner().invoke(app, ["import-linkedin", f.CREATOR, str(export), *config])
    assert result.exit_code == 0, result.output
    assert "imported 3, already imported 0" in result.output
    raw = tmp_path / "data" / f.CREATOR / "raw"
    assert (raw / "linkedin-share-7190000000000000001.json").exists()
    again = CliRunner().invoke(app, ["import-linkedin", f.CREATOR, str(export), *config])
    assert "imported 0, already imported 3" in again.output
    missing = CliRunner().invoke(app, ["import-linkedin", f.CREATOR, str(tmp_path / "x"), *config])
    assert missing.exit_code == 1
