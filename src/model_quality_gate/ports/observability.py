"""Observability ports : the A5 (audit/trace) concerns.

``ObservabilityTracerPort`` and its ``TokenUsage`` value type are NOT declared here. They come
from :mod:`hex_service_kit.observability`, where they are defined once for the whole catalog, for
the same reason ``IdentityPort`` does: every repo that hand-copied this Protocol became a separate
Protocol, and only one copy of a Protocol gets fixed when a defect is found. The import is
typing-only, so the offline profile pays nothing for it: no OpenTelemetry, no HTTP client, no
cloud SDK. The OpenTelemetry implementation lives in ``hex_service_kit.tracing`` behind the
``otel`` extra and is reached only by the ``gcp`` adapter.

``AuditSinkPort`` stays declared here on purpose. It is typed in this repo's own vocabulary (it
takes this repo's :class:`~model_quality_gate.domain.models.AuditEvent` and returns the WORM
record id), so it is not a shared shape to be centralised.

Primary GCP adapters: **Cloud Logging locked WORM bucket** for immutable audit (every gate / eval
/ red-team action), and **Cloud Trace via OpenTelemetry** for the evaluation loop traces
(message-content capture OFF). In the full platform these delegate to the shared
``agent-observability`` service over HTTP.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from hex_service_kit.observability import ObservabilityTracerPort as ObservabilityTracerPort
from hex_service_kit.observability import TokenUsage as TokenUsage

from ..domain.models import AuditEvent


@runtime_checkable
class AuditSinkPort(Protocol):
    def record(self, event: AuditEvent) -> str:
        """Write an immutable audit record (WORM)."""
        ...


__all__ = ["AuditSinkPort", "ObservabilityTracerPort", "TokenUsage"]
