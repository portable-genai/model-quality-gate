"""Remote-platform audit adapter : thin HTTP client to A5.

In the full platform deployment, immutable audit records are written through the shared
``agent-observability`` service (WORM Cloud Logging locked bucket + Cloud Trace +
FinOps) instead of A4 calling Cloud Logging directly. This adapter implements
:class:`AuditSinkPort` by POSTing the :class:`AuditEvent` to the observability service's
``/v1/audit`` endpoint, which returns ``202 Accepted`` (SPEC §6, A5 contract).

A4 evaluates models, not customer data, so the event body it sends carries the target ref
and a verdict summary, never user data. The base URL is read from ``HRZ_OBSERVABILITY_URL``
with a localhost default.
"""

from __future__ import annotations

import hashlib

import httpx

from ...domain.errors import AiQualityError
from ...domain.models import AuditEvent
from ...domain.serialization import to_jsonable
from . import _s2s

_DEFAULT_URL = "http://localhost:8085"
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class RemoteAuditError(AiQualityError):
    """Raised when the remote observability service returns a non-2xx response."""


class RemoteAuditAdapter:
    """HTTP client for the A5 ``agent-observability`` audit sink."""

    def __init__(self, settings: object) -> None:
        self._settings = settings
        self._base_url = _s2s.env_url(
            "HRZ_OBSERVABILITY_URL", _DEFAULT_URL, service="observability sink"
        )

    def record(self, event: AuditEvent) -> str:
        """Write an immutable audit record (WORM) via A5."""
        payload = to_jsonable(event)
        url = f"{self._base_url}/v1/audit"
        digest = hashlib.sha256(repr(sorted(payload.items())).encode("utf-8")).hexdigest()
        idempotency_key = f"hrz4:{event.action}:{event.run_id or digest}"
        try:
            headers = {
                **_s2s.headers(settings=self._settings, base_url=self._base_url),
                "Idempotency-Key": idempotency_key,
            }
            response = httpx.post(url, json=payload, timeout=_TIMEOUT, headers=headers)
        except httpx.HTTPError as exc:  # network / connection / timeout
            raise RemoteAuditError(f"observability audit request to {url} failed: {exc}") from exc
        if response.status_code // 100 != 2:
            raise RemoteAuditError(
                f"observability audit {url} returned {response.status_code}: {response.text[:500]}"
            )
        body = response.json()
        event_id = body.get("event_id") if isinstance(body, dict) else None
        if not isinstance(event_id, str) or not event_id.strip():
            raise RemoteAuditError("observability audit response omitted its stable event_id")
        return event_id
