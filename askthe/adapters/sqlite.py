"""SQLite adapters: the knowledge store, and full-text search with FTS5.

Records are stored as JSON with a few indexed columns for lookups, so schema changes
in docs/DATA_MODEL.md rarely need a migration. The whole database is derived data:
delete it and rebuild from the raw archive at any time.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable, Sequence
from pathlib import Path

import numpy as np
from pydantic import BaseModel

from askthe.core.interfaces import (
    DocKind,
    SearchDoc,
    SearchHit,
    SearchQuery,
    VectorHit,
    VectorItem,
)
from askthe.core.models import (
    AnswerLog,
    Claim,
    Entity,
    ProductVersion,
    Segment,
    Video,
    VideoProfile,
)


def connect(path: Path | str) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    # Shared across the web app's worker threads; this SQLite is built serialized.
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


_STORE_SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    id TEXT PRIMARY KEY, creator_id TEXT NOT NULL, published_at TEXT NOT NULL, json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS videos_creator ON videos (creator_id, published_at);
CREATE TABLE IF NOT EXISTS segments (
    id TEXT PRIMARY KEY, video_id TEXT NOT NULL, idx INTEGER NOT NULL, json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS segments_video ON segments (video_id, idx);
CREATE TABLE IF NOT EXISTS profiles (video_id TEXT PRIMARY KEY, json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY, creator_id TEXT NOT NULL, json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS entities_creator ON entities (creator_id);
CREATE TABLE IF NOT EXISTS versions (
    id TEXT PRIMARY KEY, entity_id TEXT NOT NULL, json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS versions_entity ON versions (entity_id);
CREATE TABLE IF NOT EXISTS claims (
    id TEXT PRIMARY KEY, video_id TEXT NOT NULL, seq INTEGER NOT NULL, json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS claims_video ON claims (video_id, seq);
CREATE TABLE IF NOT EXISTS claim_entities (
    claim_id TEXT NOT NULL REFERENCES claims (id) ON DELETE CASCADE,
    entity_id TEXT NOT NULL, PRIMARY KEY (claim_id, entity_id));
CREATE INDEX IF NOT EXISTS claim_entities_entity ON claim_entities (entity_id);
CREATE TABLE IF NOT EXISTS answers (
    id TEXT PRIMARY KEY, creator_id TEXT NOT NULL, asked_at TEXT NOT NULL, json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS answers_creator ON answers (creator_id, asked_at);
"""


def _load[M: BaseModel](model: type[M], rows: Iterable[tuple[str]]) -> list[M]:
    return [model.model_validate_json(row[0]) for row in rows]


class SqliteKnowledgeStore:
    def __init__(self, path: Path | str) -> None:
        self._db = connect(path)
        self._db.executescript(_STORE_SCHEMA)

    def upsert_video(self, video: Video) -> None:
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO videos VALUES (?, ?, ?, ?)",
                (
                    video.id,
                    video.creator_id,
                    video.published_at.isoformat(),
                    video.model_dump_json(),
                ),
            )

    def get_video(self, video_id: str) -> Video | None:
        rows = self._db.execute("SELECT json FROM videos WHERE id = ?", (video_id,))
        return next(iter(_load(Video, rows)), None)

    def list_videos(self, creator_id: str) -> list[Video]:
        rows = self._db.execute(
            "SELECT json FROM videos WHERE creator_id = ? ORDER BY published_at, id", (creator_id,)
        )
        return _load(Video, rows)

    def replace_segments(self, video_id: str, segments: Sequence[Segment]) -> None:
        _check_belongs(video_id, segments)
        with self._db:
            self._db.execute("DELETE FROM segments WHERE video_id = ?", (video_id,))
            self._db.executemany(
                "INSERT INTO segments VALUES (?, ?, ?, ?)",
                [(s.id, s.video_id, s.index, s.model_dump_json()) for s in segments],
            )

    def get_segments(self, video_id: str) -> list[Segment]:
        rows = self._db.execute(
            "SELECT json FROM segments WHERE video_id = ? ORDER BY idx", (video_id,)
        )
        return _load(Segment, rows)

    def get_segment(self, segment_id: str) -> Segment | None:
        rows = self._db.execute("SELECT json FROM segments WHERE id = ?", (segment_id,))
        return next(iter(_load(Segment, rows)), None)

    def save_profile(self, profile: VideoProfile) -> None:
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO profiles VALUES (?, ?)",
                (profile.video_id, profile.model_dump_json()),
            )

    def get_profile(self, video_id: str) -> VideoProfile | None:
        rows = self._db.execute("SELECT json FROM profiles WHERE video_id = ?", (video_id,))
        return next(iter(_load(VideoProfile, rows)), None)

    def upsert_entity(self, entity: Entity) -> None:
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO entities VALUES (?, ?, ?)",
                (entity.id, entity.creator_id, entity.model_dump_json()),
            )

    def get_entity(self, entity_id: str) -> Entity | None:
        rows = self._db.execute("SELECT json FROM entities WHERE id = ?", (entity_id,))
        return next(iter(_load(Entity, rows)), None)

    def list_entities(self, creator_id: str) -> list[Entity]:
        rows = self._db.execute(
            "SELECT json FROM entities WHERE creator_id = ? ORDER BY id", (creator_id,)
        )
        return _load(Entity, rows)

    def upsert_version(self, version: ProductVersion) -> None:
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO versions VALUES (?, ?, ?)",
                (version.id, version.entity_id, version.model_dump_json()),
            )

    def list_versions(self, entity_id: str) -> list[ProductVersion]:
        rows = self._db.execute(
            "SELECT json FROM versions WHERE entity_id = ? ORDER BY id", (entity_id,)
        )
        return _load(ProductVersion, rows)

    def replace_claims(self, video_id: str, claims: Sequence[Claim]) -> None:
        _check_belongs(video_id, claims)
        with self._db:
            self._db.execute("DELETE FROM claims WHERE video_id = ?", (video_id,))
            self._db.executemany(
                "INSERT INTO claims VALUES (?, ?, ?, ?)",
                [(c.id, c.video_id, i, c.model_dump_json()) for i, c in enumerate(claims)],
            )
            self._db.executemany(
                "INSERT INTO claim_entities VALUES (?, ?)",
                [(c.id, e) for c in claims for e in dict.fromkeys(c.entity_ids)],
            )

    def get_claims_for_video(self, video_id: str) -> list[Claim]:
        rows = self._db.execute(
            "SELECT json FROM claims WHERE video_id = ? ORDER BY seq", (video_id,)
        )
        return _load(Claim, rows)

    def get_claims_for_entity(self, entity_id: str) -> list[Claim]:
        rows = self._db.execute(
            "SELECT c.json FROM claims c JOIN claim_entities ce ON ce.claim_id = c.id "
            "WHERE ce.entity_id = ? ORDER BY c.video_id, c.seq",
            (entity_id,),
        )
        return _load(Claim, rows)

    def log_answer(self, log: AnswerLog) -> None:
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO answers VALUES (?, ?, ?, ?)",
                (log.id, log.creator_id, log.asked_at.isoformat(), log.model_dump_json()),
            )

    def get_answer(self, answer_id: str) -> AnswerLog | None:
        rows = self._db.execute("SELECT json FROM answers WHERE id = ?", (answer_id,))
        found = _load(AnswerLog, rows)
        return found[0] if found else None

    def list_answers(self, creator_id: str) -> list[AnswerLog]:
        rows = self._db.execute(
            "SELECT json FROM answers WHERE creator_id = ? ORDER BY asked_at, id", (creator_id,)
        )
        return _load(AnswerLog, rows)


def _check_belongs(video_id: str, records: Sequence[Segment | Claim]) -> None:
    stray = [r.id for r in records if r.video_id != video_id]
    if stray:
        raise ValueError(f"records {stray} do not belong to video {video_id!r}")


_SEARCH_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS search_docs USING fts5 (
    id UNINDEXED, kind UNINDEXED, creator_id UNINDEXED, video_id UNINDEXED, text,
    tokenize = 'porter unicode61 remove_diacritics 2');
"""

_WORD = re.compile(r"\w+", re.UNICODE)


class SqliteSearchIndex:
    """Full-text search with SQLite FTS5: BM25 ranking, stemming, any-term matching."""

    def __init__(self, path: Path | str) -> None:
        self._db = connect(path)
        self._db.executescript(_SEARCH_SCHEMA)

    def index(self, docs: Sequence[SearchDoc]) -> None:
        with self._db:
            self._db.executemany("DELETE FROM search_docs WHERE id = ?", [(d.id,) for d in docs])
            self._db.executemany(
                "INSERT INTO search_docs VALUES (?, ?, ?, ?, ?)",
                [(d.id, d.kind.value, d.creator_id, d.video_id, d.text) for d in docs],
            )

    def remove_video(self, video_id: str) -> None:
        with self._db:
            self._db.execute("DELETE FROM search_docs WHERE video_id = ?", (video_id,))

    def search(self, query: SearchQuery) -> list[SearchHit]:
        terms = list(dict.fromkeys(_WORD.findall(query.text.lower())))
        if not terms or not query.kinds:
            return []
        match = " OR ".join(f'"{t}"' for t in terms)
        kinds = [k.value for k in query.kinds]
        placeholders = ",".join("?" * len(kinds))
        rows = self._db.execute(
            f"SELECT id, kind, video_id, bm25(search_docs) FROM search_docs "
            f"WHERE search_docs MATCH ? AND creator_id = ? AND kind IN ({placeholders}) "
            f"ORDER BY bm25(search_docs), id LIMIT ?",
            (match, query.creator_id, *kinds, query.limit),
        )
        # bm25() is lower-is-better and negative; flip it so higher scores are better.
        return [
            SearchHit(doc_id=doc_id, kind=kind, video_id=video_id, score=-rank)
            for doc_id, kind, video_id, rank in rows
        ]


_VECTOR_SCHEMA = """
CREATE TABLE IF NOT EXISTS vectors (
    id TEXT PRIMARY KEY, kind TEXT NOT NULL, creator_id TEXT NOT NULL,
    video_id TEXT NOT NULL, content_hash TEXT NOT NULL, vector BLOB NOT NULL);
CREATE INDEX IF NOT EXISTS vectors_video ON vectors (video_id);
CREATE INDEX IF NOT EXISTS vectors_creator ON vectors (creator_id, kind);
"""


class SqliteVectorIndex:
    """Vectors stored normalised as float32 blobs; search is exact cosine similarity,
    computed with numpy over the creator's vectors (kept in memory between searches).

    Exact search is fast enough for tens of thousands of chunks. Beyond that, swap in
    an approximate index (sqlite-vec, pgvector) behind the same interface.
    """

    def __init__(self, path: Path | str) -> None:
        self._db = connect(path)
        self._db.executescript(_VECTOR_SCHEMA)
        self._cache: dict[str, tuple[list[tuple[str, str, str]], np.ndarray]] = {}

    def upsert(self, items: Sequence[VectorItem]) -> None:
        rows = []
        for item in items:
            v = np.asarray(item.vector, dtype=np.float32)
            norm = float(np.linalg.norm(v))
            v = v / norm if norm else v
            rows.append(
                (
                    item.id,
                    item.kind.value,
                    item.creator_id,
                    item.video_id,
                    item.content_hash,
                    v.tobytes(),
                )
            )
        with self._db:
            self._db.executemany("INSERT OR REPLACE INTO vectors VALUES (?, ?, ?, ?, ?, ?)", rows)
        self._cache.clear()

    def content_hashes(self, video_id: str) -> dict[str, str]:
        rows = self._db.execute(
            "SELECT id, content_hash FROM vectors WHERE video_id = ?", (video_id,)
        )
        return dict(rows)

    def remove_video(self, video_id: str) -> None:
        with self._db:
            self._db.execute("DELETE FROM vectors WHERE video_id = ?", (video_id,))
        self._cache.clear()

    def remove(self, ids: Sequence[str]) -> None:
        with self._db:
            self._db.executemany("DELETE FROM vectors WHERE id = ?", [(i,) for i in ids])
        self._cache.clear()

    def _matrix(self, creator_id: str) -> tuple[list[tuple[str, str, str]], np.ndarray]:
        if creator_id not in self._cache:
            rows = self._db.execute(
                "SELECT id, kind, video_id, vector FROM vectors WHERE creator_id = ? ORDER BY id",
                (creator_id,),
            ).fetchall()
            meta = [(r[0], r[1], r[2]) for r in rows]
            matrix = (
                np.vstack([np.frombuffer(r[3], dtype=np.float32) for r in rows])
                if rows
                else np.zeros((0, 0), dtype=np.float32)
            )
            self._cache[creator_id] = (meta, matrix)
        return self._cache[creator_id]

    def search(
        self, vector: Sequence[float], creator_id: str, kinds: Sequence[DocKind], limit: int
    ) -> list[VectorHit]:
        meta, matrix = self._matrix(creator_id)
        if not meta:
            return []
        q = np.asarray(vector, dtype=np.float32)
        norm = float(np.linalg.norm(q))
        if not norm or q.shape[0] != matrix.shape[1]:
            return []
        scores = matrix @ (q / norm)
        wanted = {k.value for k in kinds}
        order = np.argsort(-scores, kind="stable")
        hits = []
        for i in order:
            doc_id, kind, video_id = meta[i]
            if kind in wanted:
                hits.append(
                    VectorHit(doc_id=doc_id, kind=kind, video_id=video_id, score=float(scores[i]))
                )
                if len(hits) == limit:
                    break
        return hits
