"""PromotionGateService : the A4 promotion gate (SPEC §5, P-08).

This is the heart of A4 and the concrete home of General Principle **P-08**
(eval-gated promotion). For a target it runs the evaluation, runs the red-team harness,
combines the two into a single PASS/FAIL :class:`GateDecision`, writes a
:class:`ModelCard` plus an MRM (model-risk management) evidence pointer, and applies the
maker-checker review policy before returning.

A target passes iff the EvalReport passed **every** metric threshold AND the
RedTeamReport blocked **every** probe it had to. A borderline pass (any metric passed by
a hair) sets ``requires_human_review`` so a model-risk officer signs off (P-06).

Pipeline (SPEC §5), wrapped in ``tracer.span`` and audited:

    tracer.span("gate.gate"):
      evaluation_service.evaluate (+ A2 grounded context)
      -> redteam_service.run
      -> combine: passed = eval.passed AND redteam.passed
      -> write ModelCard + MRM evidence (model_card_store.put)
      -> review policy -> requires_human_review
      -> audit.record(gate)
      -> GateDecision

Pure domain code : no Google Cloud / ADK imports.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import nullcontext
from dataclasses import replace
from typing import Any

from .errors import AssurancePersistenceError
from .hitl import GateReviewPolicy
from .models import (
    AuditEvent,
    Decision,
    EvalDataset,
    EvalReport,
    EvalTarget,
    GateDecision,
    ModelCard,
    MrmEvidence,
    RedTeamCase,
    RedTeamReport,
)


class PromotionGateService:
    """Combine eval + red-team into a promotion verdict. Signature fixed by SPEC §5."""

    def __init__(
        self,
        evaluation_service: Any,
        redteam_service: Any,
        model_card_store: Any,
        tracer: Any,
        audit: Any,
        review_policy: GateReviewPolicy | None = None,
    ) -> None:
        self._evaluation_service = evaluation_service
        self._redteam_service = redteam_service
        self._model_card_store = model_card_store
        self._tracer = tracer
        self._audit = audit
        self._review = review_policy or GateReviewPolicy()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def gate(
        self,
        target: EvalTarget,
        dataset: EvalDataset,
        cases: list[RedTeamCase],
        actor: str,
        thresholds: dict[str, float] | None = None,
    ) -> GateDecision:
        """Run the full promotion gate for ``target`` (SPEC §5).

        ``thresholds`` is a resolved ``{metric: bar}`` map (a vertical bundle, CD2) that
        selects the metrics and their per-bundle bars; ``None`` keeps the default
        model-risk metrics, so existing callers are unchanged.
        """
        span = self._tracer.span("gate.gate", action="gate", actor=actor, target=target.ref)
        with span if span is not None else nullcontext():
            return self._gate_inner(target, dataset, cases, actor, thresholds)

    # ------------------------------------------------------------------ #
    # Pipeline
    # ------------------------------------------------------------------ #
    def _gate_inner(
        self,
        target: EvalTarget,
        dataset: EvalDataset,
        cases: list[RedTeamCase],
        actor: str,
        thresholds: dict[str, float] | None = None,
    ) -> GateDecision:
        # 1) Evaluate (grounded; pulls A2 reference context internally).
        eval_report: EvalReport = self._evaluation_service.evaluate(
            target, dataset, actor, thresholds=thresholds
        )

        # 2) Red-team.
        redteam_report: RedTeamReport = self._redteam_service.run(target, cases, actor)

        # 3) Combine: promotion requires quality, safety, and managed attestation.
        # A functional laptop evaluator can score the same corpus but is never release
        # authority merely because its deterministic metrics pass.
        passed = eval_report.passed and eval_report.attested and redteam_report.passed

        # 4) Build stable evidence references. Persistence happens after the immutable
        # audit write so its server-issued event ID is part of the run artifact.
        model_card = self._build_model_card(target, eval_report)
        model_card_ref = model_card.ref
        if not eval_report.run_id.strip():
            raise AssurancePersistenceError(
                "promotion verdict withheld: evaluation run_id is empty"
            )
        mrm_ref = f"/v1/mrm-evidence/{eval_report.run_id}"

        # 5) Maker-checker review policy (P-06): borderline passes are reviewed.
        metric_scores = {r.metric: (r.score, r.threshold) for r in eval_report.results}
        redteam_near_miss = self._redteam_near_miss(redteam_report)
        requires_review = self._review.requires_review(
            passed=passed,
            metric_scores=metric_scores,
            redteam_near_miss=redteam_near_miss,
        )

        caveats = self._caveats(eval_report, redteam_report, passed)

        decision = GateDecision(
            target=target,
            eval_report=eval_report,
            redteam_report=redteam_report,
            passed=passed,
            model_card_ref=model_card_ref,
            mrm_evidence_ref=mrm_ref,
            requires_human_review=requires_review,
            caveats=tuple(caveats),
        )

        # 6) Audit the verdict and append the complete, run-keyed MRM artifact.
        audit_event_id = self._audit_gate(actor, decision)
        evidence = MrmEvidence(
            run_id=eval_report.run_id,
            target=target,
            eval_report=eval_report,
            redteam_report=redteam_report,
            passed=passed,
            requires_human_review=requires_review,
            caveats=tuple(caveats),
            model_card_ref=model_card_ref,
            audit_event_id=audit_event_id,
            threshold_policy_digest=_threshold_policy_digest(eval_report),
        )
        self._persist_evidence(model_card, evidence)
        return decision

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _build_model_card(self, target: EvalTarget, eval_report: EvalReport) -> ModelCard:
        """Build the model card capturing the evaluated metrics (MRM evidence)."""
        metrics = {r.metric: r.score for r in eval_report.results}
        limitations = tuple(
            f"{r.metric} {r.score:.3f} below threshold {r.threshold:.2f}"
            for r in eval_report.results
            if not r.passed
        )
        return ModelCard(
            model=target.model,
            version=target.prompt_version,
            intended_use=(
                f"System {target.system or 'unspecified'} evaluated against dataset "
                f"{target.dataset_id} under prompt {target.prompt_version}."
            ),
            metrics=metrics,
            limitations=limitations,
            owner="model-risk",
        )

    def _persist_evidence(self, model_card: ModelCard, evidence: MrmEvidence) -> None:
        """Persist a model card index and immutable, run-keyed MRM evidence.

        A store failure is a hard error.  A logical reference that was never made durable
        is not MRM evidence and cannot support a promotion PASS.
        """
        try:
            current = self._model_card_store.get(model_card.model, model_card.version)
            prior_refs = current.mrm_evidence_refs if current is not None else ()
            indexed = replace(
                model_card,
                mrm_evidence_refs=tuple(dict.fromkeys((*prior_refs, evidence.ref))),
            )
            self._model_card_store.put_evidence(evidence)
            self._model_card_store.put(indexed)
        except Exception as exc:  # noqa: BLE001 - convert adapter failure to domain contract
            raise AssurancePersistenceError(
                f"promotion verdict withheld: model-card evidence persistence failed: {exc}"
            ) from exc

    @staticmethod
    def _redteam_near_miss(report: RedTeamReport) -> bool:
        """True if any probe was blocked but its detail flags a marginal outcome."""
        return any(r.passed and ("marginal" in (r.detail or "").lower()) for r in report.results)

    @staticmethod
    def _caveats(
        eval_report: EvalReport,
        redteam_report: RedTeamReport,
        passed: bool,
    ) -> list[str]:
        caveats: list[str] = []
        if not eval_report.passed:
            failed = [r.metric for r in eval_report.results if not r.passed]
            caveats.append(f"eval metrics below threshold: {', '.join(failed)}")
        if eval_report.passed and not eval_report.attested:
            caveats.append("evaluation passed but is not attested promotion evidence")
        if not redteam_report.passed:
            failed = [r.case.category.value for r in redteam_report.results if not r.passed]
            caveats.append(f"red-team probes not safely handled: {', '.join(failed)}")
        if passed:
            caveats.append("promotion gate passed; see model card for MRM evidence")
        return caveats

    def _audit_gate(self, actor: str, decision: GateDecision) -> str:
        verdict = "PASS" if decision.passed else "FAIL"
        audit_decision = (
            Decision.ESCALATED
            if decision.requires_human_review
            else (Decision.ALLOWED if decision.passed else Decision.BLOCKED)
        )
        event = AuditEvent(
            action="gate",
            actor=actor,
            decision=audit_decision,
            redacted_prompt=f"gate {verdict} for {decision.target.ref}",
            redacted_response=decision.model_card_ref,
            run_id=decision.eval_report.run_id or None,
            metadata={
                "target": decision.target.ref,
                "passed": str(decision.passed).lower(),
                "requires_human_review": str(decision.requires_human_review).lower(),
                "model_card_ref": decision.model_card_ref,
                "mrm_evidence_ref": decision.mrm_evidence_ref,
            },
        )
        try:
            event_id = self._audit.record(event)
        except Exception as exc:  # noqa: BLE001 - convert adapter failure to domain contract
            raise AssurancePersistenceError(
                f"promotion verdict withheld: immutable gate audit persistence failed: {exc}"
            ) from exc
        if not isinstance(event_id, str) or not event_id.strip():
            raise AssurancePersistenceError(
                "promotion verdict withheld: immutable audit did not return an event ID"
            )
        return event_id


def _threshold_policy_digest(report: EvalReport) -> str:
    policy = {result.metric: result.threshold for result in report.results}
    encoded = json.dumps(policy, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()
