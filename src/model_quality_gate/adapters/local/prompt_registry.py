"""Local prompt-registry adapter (PromptRegistryPort) : SQLite store.

The ``local`` profile's stand-in for the **BigQuery / GCS prompt store**: a small SQLite
table of versioned, checksummed prompts (the MRM change-control record), seedable and
deterministic. SDK-free and unconditional (no emulator benefits this offline path).

Default DB path is under a per-package local dir (``~/.model_quality_gate/registry.db``); tests
pass ``:memory:`` for an ephemeral, deterministic store.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from ...config import Settings
from ...domain.models import PromptVersion, utcnow

_DEFAULT_DB_DIR = Path.home() / ".model_quality_gate"
_DEFAULT_REGISTRY_PATH = _DEFAULT_DB_DIR / "registry.db"


class LocalPromptRegistryAdapter:
    """SQLite prompt registry: store and resolve versioned, checksummed prompts."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        path = getattr(getattr(settings, "local", None), "registry_path", "") or str(
            _DEFAULT_REGISTRY_PATH
        )
        if path not in (":memory:", "") and not path.startswith("file:"):
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        # ``check_same_thread=False`` + a lock keeps the single process-wide connection
        # (deps.get_container is lru_cached) usable from Starlette's sync-endpoint worker
        # threadpool: put()/get()/list() may run on a worker thread other than the one that
        # opened the connection. The lock serialises that access (single-writer).
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS prompts (
                name TEXT NOT NULL,
                version TEXT NOT NULL,
                template TEXT NOT NULL,
                checksum TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (name, version)
            )
            """
        )
        self._conn.commit()

    def put(self, version: PromptVersion) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO prompts (name, version, template, checksum, created_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(name, version) DO UPDATE SET "
                "template=excluded.template, checksum=excluded.checksum, "
                "created_at=excluded.created_at",
                (
                    version.name,
                    version.version,
                    version.template,
                    version.checksum,
                    version.created_at.isoformat(),
                ),
            )
            self._conn.commit()

    def get(self, name: str, version: str) -> PromptVersion | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM prompts WHERE name = ? AND version = ?", (name, version)
            ).fetchone()
        return self._row_to_prompt(row) if row else None

    def list(self, name: str) -> list[PromptVersion]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM prompts WHERE name = ? ORDER BY created_at DESC", (name,)
            ).fetchall()
        return [self._row_to_prompt(row) for row in rows]

    @staticmethod
    def _row_to_prompt(row: sqlite3.Row) -> PromptVersion:
        try:
            created = datetime.fromisoformat(row["created_at"])
        except (TypeError, ValueError):
            created = utcnow()
        return PromptVersion(
            name=row["name"],
            version=row["version"],
            template=row["template"],
            checksum=row["checksum"] or "",
            created_at=created,
        )
