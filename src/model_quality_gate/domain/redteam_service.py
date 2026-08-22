"""RedTeamService : adversarial red-team harness orchestration (SPEC §5).

For a target, runs a set of adversarial probes (prompt-injection, jailbreak,
PII-exfiltration, harmful-content, hallucination) through the ``RedTeamPort`` (a
Gemini-driven harness in the gcp profile, a deterministic backend in tests) and
assembles a :class:`RedTeamReport` with a pass/fail per probe and an overall verdict.

A probe *passes* when the target behaved safely: it blocked / refused a probe that
should be blocked, and did not fabricate for a hallucination probe. The report passes
only when every probe passed.

Pipeline (SPEC §5), wrapped in ``tracer.span`` and audited:

    tracer.span("redteam.run"):
      run each RedTeamCase through the RedTeamPort
      -> assemble RedTeamReport
      -> audit.record(redteam)

Pure domain code : no Google Cloud / ADK imports.
"""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any

from .errors import AssurancePersistenceError
from .models import (
    AuditEvent,
    Decision,
    EvalTarget,
    RedTeamCase,
    RedTeamReport,
    RedTeamResult,
)


class RedTeamService:
    """Run an adversarial red-team harness over a target. Signature fixed by SPEC §5."""

    def __init__(
        self,
        redteam: Any,
        tracer: Any,
        audit: Any,
    ) -> None:
        self._redteam = redteam
        self._tracer = tracer
        self._audit = audit

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def run(
        self,
        target: EvalTarget,
        cases: list[RedTeamCase],
        actor: str,
    ) -> RedTeamReport:
        """Run ``cases`` against ``target`` for ``actor`` (SPEC §5)."""
        span = self._tracer.span("redteam.run", action="redteam", actor=actor, target=target.ref)
        with span if span is not None else nullcontext():
            return self._run_inner(target, cases, actor)

    # ------------------------------------------------------------------ #
    # Pipeline
    # ------------------------------------------------------------------ #
    def _run_inner(
        self,
        target: EvalTarget,
        cases: list[RedTeamCase],
        actor: str,
    ) -> RedTeamReport:
        results = self._run_cases(target, cases)
        report = RedTeamReport(target=target, results=results)

        decision = Decision.ALLOWED if report.passed else Decision.BLOCKED
        n_passed = sum(1 for r in results if r.passed)
        summary = f"red-teamed {target.ref}: {n_passed}/{len(results)} probes safe"
        self._write_audit(actor, target, decision, summary, len(results))
        return report

    def _run_cases(
        self,
        target: EvalTarget,
        cases: list[RedTeamCase],
    ) -> tuple[RedTeamResult, ...]:
        """Delegate the probes to the RedTeamPort, defensively.

        The port returns a ``RedTeamReport`` for the whole batch; if it fails or returns
        an unusable shape we synthesise a failing result per probe (a red-team backend
        failure must never look like every probe passed).

        ``NotImplementedError`` is allowed to propagate: it is the on-prem placeholder
        signalling "no harness wired up", which must surface as a clean profile error (the
        CLI maps it to exit code 2). Any *other* backend fault degrades to a failing report.
        """
        try:
            backend_report = self._redteam.run(target, list(cases))
            backend_results = getattr(backend_report, "results", None)
        except NotImplementedError:
            raise
        except Exception:  # noqa: BLE001 - a backend fault is a failing report, not a crash
            backend_results = None

        if backend_results:
            return tuple(backend_results)

        # Defensive synthesis: every probe is treated as not-safely-handled.
        return tuple(
            RedTeamResult(
                case=case,
                blocked=False,
                detail="red-team backend unavailable; probe treated as unhandled",
                passed=False,
            )
            for case in cases
        )

    # ------------------------------------------------------------------ #
    # Audit
    # ------------------------------------------------------------------ #
    def _write_audit(
        self,
        actor: str,
        target: EvalTarget,
        decision: Decision,
        summary: str,
        n: int,
    ) -> None:
        event = AuditEvent(
            action="redteam",
            actor=actor,
            decision=decision,
            redacted_prompt=summary,
            redacted_response=target.ref,
            metadata={"target": target.ref, "n_cases": str(n)},
        )
        try:
            self._audit.record(event)
        except Exception as exc:  # noqa: BLE001 - convert adapter failure to domain contract
            raise AssurancePersistenceError(
                f"red-team evidence was computed but immutable audit persistence failed: {exc}"
            ) from exc
