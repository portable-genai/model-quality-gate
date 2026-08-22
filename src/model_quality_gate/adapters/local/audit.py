"""Local audit adapter (AuditSinkPort) : append-only, hash-chained local WORM stand-in.

The ``local`` profile's stand-in for the **Cloud Logging locked WORM bucket**. Sourced
from the shared ``hex-service-kit`` commons: the store is
:class:`hex_service_kit.audit.HashChainedAuditLog`, an append-only SQLite table (or
in-memory for ``:memory:``) where every record is chained to its predecessor
(``entry_hash = SHA-256(prev_hash || "\\n" || event_json)``) and UPDATE/DELETE are
rejected by triggers. The trail exports to / restores from JSON Lines with the chain
re-verified line by line.

Honest limits (C9): ``verify_chain`` catches in-place edits, interior deletions and
reordering; it cannot by itself detect a truncated tail or a full rewrite by an actor
with file write access. The managed profile's locked WORM bucket provides
non-rewritability itself.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

from hex_service_kit import ChainReport, HashChainedAuditLog

from ...config import Settings
from ...domain.models import AuditEvent

_DEFAULT_AUDIT_PATH = Path.home() / ".model_quality_gate" / "audit.db"


class LocalAppendOnlyAuditAdapter:
    """Append-only, hash-chained audit store: gate / eval / red-team events, read-back."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        path = getattr(getattr(settings, "local", None), "audit_path", "") or str(
            _DEFAULT_AUDIT_PATH
        )
        self._log = HashChainedAuditLog(path)

    def record(self, event: AuditEvent) -> str:
        """Append one immutable audit record (no update / delete)."""
        event_id = event.event_id or _event_id(event)
        self._log.record(replace(event, event_id=event_id))
        return event_id

    def read_all(self) -> list[dict]:
        """Read back every stored event (newest last) for inspection / assertions."""
        return self._log.read_all()

    def verify_chain(self) -> ChainReport:
        """Verify the hash chain over the stored trail (tamper evidence, C9)."""
        return self._log.verify_chain()

    def export_jsonl(self, path: str | Path) -> int:
        """Export the open JSONL evidence format with chain hashes."""
        return self._log.export_jsonl(path)

    def import_jsonl(self, path: str | Path) -> int:
        """Restore a verified JSONL trail into an empty local store."""
        return self._log.import_jsonl(path)


def _event_id(event: AuditEvent) -> str:
    seed = f"{event.action}|{event.run_id or ''}|{event.actor}|{event.redacted_prompt}"
    return "audit-" + hashlib.sha256(seed.encode()).hexdigest()[:32]
