"""Local knowledge-base adapter (KnowledgeBaseClientPort) : SQLite FTS5 retrieval.

The ``local`` profile's stand-in for the **A2 Enterprise Knowledge Base**: a ``sqlite3``
database with an **FTS5** virtual table over the reference passages, queried with BM25
(``ORDER BY rank``). It is SDK-free, deterministic and **seedable**, so the same code
grounds the offline gate run and the unit tests. Under ``local`` this platform client uses
an in-process SQLite index rather than HTTP to the sibling A2 service (a laptop runs one
app, not the whole platform). There is no Google emulator for enterprise search, so this
path is unconditional.

The adapter returns the same :class:`Citation` objects with page-level provenance as the
managed / remote adapter, preserving interface parity. It self-seeds from the built-in
synthetic corpus on first use so an out-of-the-box local gate run grounds against
reference context without any ingestion step; callers may also ``seed(citations)`` their
own corpus.

Default DB path is under a per-package local dir (``~/.model_quality_gate/local.db``); tests pass
``:memory:`` for an ephemeral, deterministic index.
"""

from __future__ import annotations

import re
import sqlite3
import threading
from pathlib import Path

from ...config import Settings
from ...domain.models import Citation

# Default on-disk location for the local index (overridable via settings.local.db_path).
_DEFAULT_DB_DIR = Path.home() / ".model_quality_gate"
_DEFAULT_DB_PATH = _DEFAULT_DB_DIR / "local.db"

# FTS5 query syntax is strict; keep only word characters so a free-text query never trips
# an "fts5: syntax error" (e.g. on punctuation), and OR the terms for recall.
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


class LocalFtsKnowledgeBaseAdapter:
    """Retrieve grounded reference citations from a local SQLite FTS5 index (BM25 ranked)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        db_path = getattr(getattr(settings, "local", None), "db_path", "") or str(_DEFAULT_DB_PATH)
        self._db_path = db_path
        # ``check_same_thread=False`` + a lock keeps the single process-wide connection
        # (deps.get_container is lru_cached) usable from Starlette's sync-endpoint worker
        # threadpool: a request handled on another worker thread calls seed()/add()/
        # retrieve() on a connection opened in __init__'s thread. The lock serialises that
        # access (single-writer) so cross-thread use does not raise.
        self._lock = threading.Lock()
        self._conn = self._connect(db_path)
        self._init_schema()
        # Self-seed the built-in corpus so an out-of-the-box local run is grounded.
        if self._is_empty():
            from ._seed import SEED_CITATIONS

            self.seed(SEED_CITATIONS)

    # ------------------------------------------------------------------ #
    # Connection / schema
    # ------------------------------------------------------------------ #
    @staticmethod
    def _connect(db_path: str) -> sqlite3.Connection:
        if db_path not in (":memory:", "") and not db_path.startswith("file:"):
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        # One FTS5 table holds the searchable text; citation metadata rides alongside as
        # UNINDEXED columns so a single query returns everything needed to cite a hit.
        with self._lock:
            self._conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS passages USING fts5(
                    text,
                    source_id UNINDEXED,
                    title UNINDEXED,
                    url UNINDEXED,
                    page UNINDEXED,
                    score UNINDEXED,
                    acl_tags UNINDEXED
                )
                """
            )
            self._conn.commit()

    def _is_empty(self) -> bool:
        with self._lock:
            row = self._conn.execute("SELECT count(*) AS n FROM passages").fetchone()
        return int(row["n"]) == 0

    # ------------------------------------------------------------------ #
    # Seeding / ingestion
    # ------------------------------------------------------------------ #
    def seed(self, citations: tuple[Citation, ...] | list[Citation]) -> int:
        """Replace the index contents with ``citations`` (deterministic test/CLI seed)."""
        with self._lock:
            self._conn.execute("DELETE FROM passages")
            self._conn.commit()
        return self._insert(list(citations))

    def add(self, citations: list[Citation]) -> int:
        """Append ``citations`` to the index without clearing existing rows."""
        return self._insert(citations)

    def _insert(self, citations: list[Citation]) -> int:
        rows = []
        for c in citations:
            rows.append(
                (
                    c.snippet or c.title,
                    c.source_id,
                    c.title,
                    c.url,
                    "" if c.page is None else str(c.page),
                    "" if c.score is None else f"{c.score:.6f}",
                    ",".join(c.acl_tags),
                )
            )
        with self._lock:
            self._conn.executemany(
                "INSERT INTO passages (text, source_id, title, url, page, score, acl_tags) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            self._conn.commit()
        return len(rows)

    # ------------------------------------------------------------------ #
    # KnowledgeBaseClientPort
    # ------------------------------------------------------------------ #
    def retrieve(self, query: str, top_k: int = 5) -> list[Citation]:
        """Return ranked reference citations for ``query`` from the local FTS5 index."""
        match = self._build_match(query)
        with self._lock:
            if not match:
                # No usable query terms: fall back to a score-ordered scan so the pipeline
                # still gets something deterministic rather than an FTS5 syntax error.
                cursor = self._conn.execute(
                    "SELECT * FROM passages ORDER BY score DESC LIMIT ?", (max(top_k, 1),)
                )
            else:
                cursor = self._conn.execute(
                    "SELECT * FROM passages WHERE passages MATCH ? ORDER BY rank LIMIT ?",
                    (match, max(top_k, 1)),
                )
            rows = cursor.fetchall()
        return [self._row_to_citation(row) for row in rows]

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _build_match(text: str) -> str:
        """Build a safe FTS5 MATCH expression: OR of the alphanumeric query tokens."""
        tokens = _TOKEN_RE.findall(text or "")
        if not tokens:
            return ""
        # Quote each token so reserved words (AND/OR/NOT/NEAR) are treated as literals.
        return " OR ".join(f'"{t}"' for t in tokens)

    @staticmethod
    def _row_to_citation(row: sqlite3.Row) -> Citation:
        page_raw = row["page"]
        page = int(page_raw) if page_raw not in (None, "") else None
        score_raw = row["score"]
        try:
            score = float(score_raw) if score_raw not in (None, "") else None
        except (TypeError, ValueError):
            score = None
        acl = row["acl_tags"] or ""
        return Citation(
            source_id=row["source_id"],
            title=row["title"],
            url=row["url"],
            page=page,
            snippet=row["text"] or "",
            score=score,
            acl_tags=tuple(t for t in acl.split(",") if t),
        )
