from pathlib import Path

from typer.testing import CliRunner

from askthe.adapters.files import FileRawArchive
from askthe.adapters.memory import (
    MemoryCatalogSource,
    MemoryKnowledgeStore,
    MemoryRawArchive,
    MemorySearchIndex,
    MemoryTranscriptSource,
)
from askthe.cli import app
from askthe.core.interfaces import SearchQuery
from askthe.pipeline.fetch import fetch_videos
from askthe.pipeline.segment import segment_videos
from tests import factories as f

REPO = Path(__file__).resolve().parent.parent


def sources(*platform_ids: str):
    catalog, transcripts = MemoryCatalogSource(), MemoryTranscriptSource()
    for pid in platform_ids:
        catalog.add(f.CREATOR, f.meta(pid))
        transcripts.add(pid, f.transcript(f"warm boots review {pid}. " * 50))
    return catalog, transcripts


def test_fetch_archives_new_videos_skips_existing_and_reports_failures():
    creator = f.creator()
    catalog, transcripts = sources("a", "b")
    archive = MemoryRawArchive()
    archive.save(f.raw_video("a"))

    report = fetch_videos(
        creator, ["a", "b", "missing"], catalog, transcripts, archive, source="test"
    )
    assert report.skipped == ["a"]
    assert report.fetched == ["b"]
    assert list(report.failed) == ["missing"]
    assert archive.list_ids(f.CREATOR) == ["a", "b"]
    assert archive.load(f.CREATOR, "b").source == "test"


def test_segment_rebuilds_store_and_index_from_raw():
    creator = f.creator()
    catalog, transcripts = sources("a", "b")
    archive, store, search = MemoryRawArchive(), MemoryKnowledgeStore(), MemorySearchIndex()
    fetch_videos(creator, ["a", "b"], catalog, transcripts, archive, source="test")

    first = segment_videos(creator, archive, store, search)
    again = segment_videos(creator, archive, store, search)
    assert first == again and first.videos == 2 and first.segments > 2
    assert [v.platform_id for v in store.list_videos(f.CREATOR)] == ["a", "b"]

    hits = search.search(SearchQuery(text="warm boots", creator_id=f.CREATOR))
    assert {h.video_id for h in hits} == {"test-creator:a", "test-creator:b"}
    # Every segment found in search exists in the store.
    assert all(store.get_segment(h.doc_id) for h in hits)


def test_cli_segment_and_status_on_disk(tmp_path):
    (tmp_path / "creators").mkdir()
    (tmp_path / "creators" / f"{f.CREATOR}.yaml").write_text(
        f.creator().model_dump_json()  # JSON is valid YAML
    )
    (tmp_path / "askthe.toml").write_text(
        'data_dir = "data"\ncreators_dir = "creators"\n'
        + "".join(
            f'[adapters.{port}]\nuse = "{use}"\n'
            for port, use in {
                "catalog": "memory",
                "transcripts": "memory",
                "raw_archive": "files",
                "store": "sqlite",
                "search": "sqlite",
                "llm": "memory",
            }.items()
        )
    )
    FileRawArchive(tmp_path / "data").save(f.raw_video("abc"))
    config = ["--config", str(tmp_path / "askthe.toml")]
    runner = CliRunner()

    result = runner.invoke(app, ["segment", f.CREATOR, *config])
    assert result.exit_code == 0, result.output
    assert "segmented 1 videos into 1 segments" in result.output

    result = runner.invoke(app, ["status", f.CREATOR, *config])
    assert result.exit_code == 0, result.output
    assert "1 raw videos" in result.output and "1 videos, 1 segments" in result.output

    result = runner.invoke(app, ["fetch", f.CREATOR, *config])
    assert result.exit_code == 1  # nothing selected
    assert "no videos to fetch" in result.output


def test_catalog_lists_videos_with_titles_oldest_first():
    catalog, _ = sources("a", "b")
    listing = catalog.list_videos(f.creator())
    assert [(v.platform_id, v.title) for v in listing] == [("a", "Video a"), ("b", "Video b")]


def test_fetch_stops_after_consecutive_failures_and_keeps_errors_short():
    catalog, transcripts = sources("a")

    class Blocked:
        def get_transcript(self, platform_id):
            raise RuntimeError("IpBlocked\n\nlong explanation " * 50)

    report = fetch_videos(
        f.creator(),
        ["x", "y", "z", "w"],
        catalog,
        Blocked(),
        MemoryRawArchive(),
        source="test",
        max_consecutive_failures=2,
    )
    assert list(report.failed) == ["x", "y"] and report.stopped_early
    assert all("\n" not in msg and len(msg) <= 300 for msg in report.failed.values())

    archive = MemoryRawArchive()
    report = fetch_videos(
        f.creator(),
        ["a", "x", "a2"],
        catalog,
        transcripts,
        archive,
        source="test",
        max_consecutive_failures=2,
    )
    assert report.fetched == ["a"] and not report.stopped_early
