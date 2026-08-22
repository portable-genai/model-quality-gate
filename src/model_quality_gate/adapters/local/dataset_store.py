"""Local dataset-store adapter (DatasetStorePort) : SQLite store of golden JSONL sets.

The ``local`` profile's stand-in for the **CMEK Cloud Storage golden bucket**: a small
SQLite table mapping a dataset id to its raw JSONL bytes, so an ingested set can be
resolved and scored offline. SDK-free and unconditional.

Default DB path is under a per-package local dir (``~/.model_quality_gate/datasets.db``); tests
pass ``:memory:`` for an ephemeral, deterministic store.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from ...config import Settings

_DEFAULT_DB_DIR = Path.home() / ".model_quality_gate"
_DEFAULT_DATASETS_PATH = _DEFAULT_DB_DIR / "datasets.db"


class LocalDatasetStoreAdapter:
    """SQLite dataset store: ingest and resolve golden JSONL datasets by id."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        path = getattr(getattr(settings, "local", None), "datasets_path", "") or str(
            _DEFAULT_DATASETS_PATH
        )
        if path not in (":memory:", "") and not path.startswith("file:"):
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        # Single process-wide connection reused across Starlette worker threads (see the
        # prompt-registry adapter for the rationale); the lock serialises access.
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS datasets (
                dataset_id TEXT PRIMARY KEY,
                jsonl BLOB NOT NULL
            )
            """
        )
        self._conn.commit()

    def put(self, dataset_id: str, jsonl: bytes) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO datasets (dataset_id, jsonl) VALUES (?, ?) "
                "ON CONFLICT(dataset_id) DO UPDATE SET jsonl=excluded.jsonl",
                (dataset_id, sqlite3.Binary(jsonl)),
            )
            self._conn.commit()

    def get(self, dataset_id: str) -> bytes | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT jsonl FROM datasets WHERE dataset_id = ?", (dataset_id,)
            ).fetchone()
        return bytes(row["jsonl"]) if row else None

    def list(self) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT dataset_id FROM datasets ORDER BY dataset_id"
            ).fetchall()
        return [row["dataset_id"] for row in rows]
