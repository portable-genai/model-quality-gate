"""The local audit store is hash-chained and tamper-evident (C9).

The store itself is the shared ``hex-service-kit`` ``HashChainedAuditLog`` (its own suite
proves the chain mechanics); these tests prove THIS repo's wiring: the adapter records
domain ``AuditEvent`` objects, reads them back, and surfaces tamper verification.
"""

from __future__ import annotations

from model_quality_gate.adapters.local.audit import LocalAppendOnlyAuditAdapter
from model_quality_gate.config import LocalSettings, Settings
from model_quality_gate.domain.models import AuditEvent, Decision


def _event(action: str) -> AuditEvent:
    return AuditEvent(
        action=action,
        actor="eval-bot (FICTIONAL)",
        decision=Decision.ALLOWED,
        redacted_prompt=f"{action} on example-target (FICTIONAL)",
    )


def _adapter() -> LocalAppendOnlyAuditAdapter:
    settings = Settings(profile="local", local=LocalSettings(audit_path=":memory:"))
    return LocalAppendOnlyAuditAdapter(settings)


def test_events_round_trip_and_chain_verifies() -> None:
    adapter = _adapter()
    adapter.record(_event("evaluate"))
    adapter.record(_event("gate"))
    events = adapter.read_all()
    assert [e["action"] for e in events] == ["evaluate", "gate"]
    report = adapter.verify_chain()
    assert report.ok and report.chained == 2


def test_tampering_is_detected() -> None:
    adapter = _adapter()
    adapter.record(_event("evaluate"))
    adapter.record(_event("gate"))
    conn = adapter._log._conn  # noqa: SLF001 - deliberate tamper simulation
    conn.execute("DROP TRIGGER IF EXISTS audit_log_no_update")
    conn.execute(
        "UPDATE audit_log SET event_json = replace(event_json, 'evaluate', 'x') WHERE seq = 1"
    )
    conn.commit()
    assert not adapter.verify_chain().ok
