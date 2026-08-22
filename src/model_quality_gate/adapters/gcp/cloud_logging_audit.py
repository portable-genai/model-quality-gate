"""Cloud Logging WORM audit adapter (AuditSinkPort).

Backs the domain ``AuditSinkPort`` with **Cloud Logging** writing to a **locked WORM
bucket** (retention ~7 years, irreversible) : the immutable evidence trail for every
gate / eval / red-team action (P-07, P-08). The ``google-cloud-logging`` import is lazy
so the on-prem and test profiles import without it.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import Any

from ...config import Settings
from ...domain.models import AuditEvent
from ...domain.serialization import to_jsonable


class CloudLoggingAuditAdapter:
    """Write immutable audit records to a locked Cloud Logging WORM bucket."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._logger: Any | None = None

    def _log(self) -> Any:
        if self._logger is None:
            from google.cloud import logging as gcp_logging  # lazy

            client = gcp_logging.Client(project=self._settings.project_id)
            self._logger = client.logger(self._settings.logging.log_name)
        return self._logger

    # ------------------------------------------------------------------ #
    # AuditSinkPort
    # ------------------------------------------------------------------ #
    def record(self, event: AuditEvent) -> str:
        """Write a structured, already-safe audit record (WORM)."""
        event_id = event.event_id or _event_id(event)
        normalized = replace(event, event_id=event_id)
        payload = to_jsonable(normalized)
        self._log().log_struct(
            payload,
            severity=_severity_for(event),
            labels={
                "action": event.action,
                "decision": event.decision.value,
                "resource": event.resource,
                "event_id": event_id,
            },
            insert_id=event_id,
        )
        return event_id


def _event_id(event: AuditEvent) -> str:
    seed = f"{event.action}|{event.run_id or ''}|{event.actor}|{event.redacted_prompt}"
    return "audit-" + hashlib.sha256(seed.encode()).hexdigest()[:32]


def _severity_for(event: AuditEvent) -> str:
    from ...domain.models import Decision

    if event.decision is Decision.BLOCKED:
        return "WARNING"
    if event.decision is Decision.ESCALATED:
        return "NOTICE"
    return "INFO"
