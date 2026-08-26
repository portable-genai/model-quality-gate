"""DriftMonitorService : read recorded drift and escalate it, never act on it.

``MetricsStorePort.drift(model)`` has always computed per-metric drift signals. Until
this service existed nothing in a served process called it: the signals were computed for
a dashboard that had to be built by the reader, so an ``alert`` reached nobody. This
service is the caller, and it is deliberately the ONLY thing that reads drift on the
serving path.

Pipeline, wrapped in ``tracer.span`` and audited:

    tracer.span("drift.assess"):
      metrics_store.drift(model)
      -> DriftRegatePolicy.assess  (pure, stdlib, replayable)
      -> audit.record(drift)       (ESCALATED when a human is owed something)
      -> DriftEscalation

What this service does NOT do, by construction rather than by convention: it holds no
gate service, no model-card store and no promotion path of any kind, so an ``alert``
cannot become an executed promotion or demotion here. It raises the bar and stops. The
scheduled re-scorer that would act on the requirement, and the live-traffic sampler that
would feed the metrics table in the first place, are both absent from this repository.

Pure domain code : no Google Cloud / ADK imports.
"""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any

from .drift import DriftRegatePolicy
from .errors import AssurancePersistenceError
from .models import AuditEvent, Decision, DriftEscalation


class DriftMonitorService:
    """Assess a model's recorded quality drift and state what it owes a human."""

    def __init__(
        self,
        metrics_store: Any,
        tracer: Any,
        audit: Any,
        policy: DriftRegatePolicy | None = None,
    ) -> None:
        self._metrics_store = metrics_store
        self._tracer = tracer
        self._audit = audit
        self._policy = policy or DriftRegatePolicy()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def assess(self, model: str, actor: str) -> DriftEscalation:
        """Return the escalation ``model``'s recorded drift owes, for ``actor``.

        A store that cannot answer is allowed to raise: an unreadable metrics store is an
        unmeasured model, and reporting it as calm is the failure mode this whole path
        exists to avoid. The on-prem placeholder's ``NotImplementedError`` reaches the CLI
        as a profile error for the same reason.
        """
        span = self._tracer.span("drift.assess", action="drift", actor=actor, target=model)
        with span if span is not None else nullcontext():
            return self._assess_inner(model, actor)

    # ------------------------------------------------------------------ #
    # Pipeline
    # ------------------------------------------------------------------ #
    def _assess_inner(self, model: str, actor: str) -> DriftEscalation:
        signals = tuple(self._metrics_store.drift(model))
        escalation = self._policy.assess(model, signals)
        self._write_audit(actor, escalation)
        return escalation

    def _write_audit(self, actor: str, escalation: DriftEscalation) -> None:
        """Record the assessment. A failure withholds the escalation.

        Same rule as the gate and the evaluation: an escalation nobody can prove was
        raised is not evidence, and a model-risk finding that exists only in one HTTP
        response has not been raised at all.
        """
        event = AuditEvent(
            action="drift",
            actor=actor,
            decision=(Decision.ESCALATED if escalation.requires_human_review else Decision.ALLOWED),
            redacted_prompt=f"drift {escalation.status} for {escalation.model}",
            redacted_response=(
                "re-gate required" if escalation.requires_re_gate else "no re-gate required"
            ),
            metadata={
                "model": escalation.model,
                "status": escalation.status,
                "n_signals": str(len(escalation.signals)),
                "requires_re_gate": str(escalation.requires_re_gate).lower(),
                "requires_human_review": str(escalation.requires_human_review).lower(),
                "escalating_metrics": ",".join(escalation.escalating_metrics),
            },
        )
        try:
            self._audit.record(event)
        except Exception as exc:  # noqa: BLE001 - convert adapter failure to domain contract
            raise AssurancePersistenceError(
                f"drift escalation was computed but immutable audit persistence failed: {exc}"
            ) from exc
