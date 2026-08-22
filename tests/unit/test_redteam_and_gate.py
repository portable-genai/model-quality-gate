"""Unit tests for RedTeamService and the PromotionGateService gate logic.

SPEC §5:
* RedTeamService.run(target, cases, actor) -> RedTeamReport (passes iff every probe safe)
* PromotionGateService.gate(...) -> GateDecision (PASS iff eval.passed AND redteam.passed),
  writes a ModelCard + MRM evidence, and flags borderline passes for human review (P-06).

These tests are driven by the real ``local`` adapter family (no Google Cloud SDK). The
FAIL paths use thin local subclasses (``FixedEvaluation`` / ``UnsafeRedTeam``) that vary
the deterministic local backends' output rather than swapping in a separate fake hierarchy.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from tests.conftest import (
    FixedEvaluation,
    UnsafeRedTeam,
    load_service,
)
from tests.fixtures import sample_targets

from model_quality_gate.domain.errors import AssurancePersistenceError
from model_quality_gate.domain.models import Decision, GateDecision, RedTeamReport

ACTOR = "model-risk@bank.test"
TARGET = sample_targets.SAMPLE_TARGET
DATASET = sample_targets.SAMPLE_DATASET
CASES = sample_targets.SAMPLE_REDTEAM_CASES


# --------------------------------------------------------------------------- #
# RedTeamService
# --------------------------------------------------------------------------- #
def test_redteam_passes_when_every_probe_blocked(redteam_service, audit):
    report = redteam_service.run(TARGET, CASES, actor=ACTOR)

    assert isinstance(report, RedTeamReport)
    assert report.n_cases == len(CASES)
    assert report.passed is True
    assert all(r.blocked and r.passed for r in report.results)
    assert any(e.decision is Decision.ALLOWED for e in audit.events)


def test_redteam_fails_when_a_probe_is_not_blocked(local_settings, tracer, audit):
    service = load_service("RedTeamService")(UnsafeRedTeam(local_settings), tracer, audit)
    report = service.run(TARGET, CASES, actor=ACTOR)

    assert report.passed is False
    assert all(not r.passed for r in report.results)
    assert any(e.decision is Decision.BLOCKED for e in audit.events)


def test_redteam_is_wrapped_in_a_tracer_span(redteam_service, tracer):
    redteam_service.run(TARGET, CASES, actor=ACTOR)
    assert "redteam.run" in tracer.spans


# --------------------------------------------------------------------------- #
# PromotionGateService
# --------------------------------------------------------------------------- #
def test_gate_passes_when_both_eval_and_redteam_pass(gate_service, model_card_store):
    gate_service._evaluation_service._evaluation.attested = True
    decision = gate_service.gate(TARGET, DATASET, CASES, actor=ACTOR)

    assert isinstance(decision, GateDecision)
    assert decision.passed is True
    # A model card + MRM evidence pointer is always written (P-07).
    assert decision.model_card_ref == f"{TARGET.model}@{TARGET.prompt_version}"
    assert decision.mrm_evidence_ref.startswith("/v1/mrm-evidence/")
    assert model_card_store.puts, "the gate must persist a model card as MRM evidence"


def test_gate_keeps_distinct_runs_independently_resolvable(gate_service, model_card_store):
    gate_service._evaluation_service._evaluation.attested = True
    first = gate_service.gate(TARGET, DATASET, CASES, actor=ACTOR)
    second_target = replace(TARGET, prompt_version="v-next")
    second = gate_service.gate(second_target, DATASET, CASES, actor=ACTOR)

    assert first.eval_report.run_id != second.eval_report.run_id
    assert model_card_store.get_evidence(first.eval_report.run_id) is not None
    assert model_card_store.get_evidence(second.eval_report.run_id) is not None


def test_gate_fails_when_redteam_fails(
    local_settings, evaluation_service, model_card_store, tracer, audit
):
    redteam_service = load_service("RedTeamService")(UnsafeRedTeam(local_settings), tracer, audit)
    gate = load_service("PromotionGateService")(
        evaluation_service, redteam_service, model_card_store, tracer, audit
    )
    decision = gate.gate(TARGET, DATASET, CASES, actor=ACTOR)

    assert decision.passed is False
    assert any("red-team" in c for c in decision.caveats)


def test_gate_fails_when_eval_fails(
    local_settings, knowledge_base, llm, redteam_service, model_card_store, tracer, audit
):
    failing_eval = load_service("EvaluationService")(
        FixedEvaluation(local_settings, overrides={"safety": 0.10}),
        knowledge_base,
        llm,
        tracer,
        audit,
    )
    gate = load_service("PromotionGateService")(
        failing_eval, redteam_service, model_card_store, tracer, audit
    )
    decision = gate.gate(TARGET, DATASET, CASES, actor=ACTOR)

    assert decision.passed is False
    assert any("eval metrics" in c for c in decision.caveats)


def test_gate_flags_borderline_pass_for_human_review(
    local_settings, knowledge_base, llm, redteam_service, model_card_store, tracer, audit
):
    # groundedness threshold is 0.80; 0.805 passes but is within the 0.02 borderline band.
    borderline_eval = load_service("EvaluationService")(
        FixedEvaluation(local_settings, passing_score=0.999, overrides={"groundedness": 0.805}),
        knowledge_base,
        llm,
        tracer,
        audit,
    )
    borderline_eval._evaluation.attested = True
    gate = load_service("PromotionGateService")(
        borderline_eval, redteam_service, model_card_store, tracer, audit
    )
    decision = gate.gate(TARGET, DATASET, CASES, actor=ACTOR)

    assert decision.passed is True
    assert decision.requires_human_review is True
    # The borderline pass is audited as ESCALATED (routed to a model-risk officer).
    assert any(e.decision is Decision.ESCALATED for e in audit.events)


def test_gate_denies_unattested_evaluation_even_when_quality_and_redteam_pass(
    gate_service,
):
    decision = gate_service.gate(TARGET, DATASET, CASES, actor=ACTOR)

    assert decision.eval_report.passed is True
    assert decision.eval_report.attested is False
    assert decision.passed is False
    assert any("not attested" in caveat for caveat in decision.caveats)


def test_gate_is_wrapped_in_a_tracer_span(gate_service, tracer):
    gate_service.gate(TARGET, DATASET, CASES, actor=ACTOR)
    assert "gate.gate" in tracer.spans


def test_gate_withholds_verdict_when_model_card_evidence_is_not_durable(
    evaluation_service, redteam_service, tracer, audit
):
    class _FailingModelCardStore:
        def put(self, card):
            raise OSError("evidence bucket unavailable")

    gate = load_service("PromotionGateService")(
        evaluation_service, redteam_service, _FailingModelCardStore(), tracer, audit
    )
    with pytest.raises(AssurancePersistenceError, match="model-card evidence"):
        gate.gate(TARGET, DATASET, CASES, actor=ACTOR)


def test_gate_withholds_verdict_when_final_audit_is_not_durable(
    evaluation_service, redteam_service, model_card_store, tracer
):
    class _FailOnGateAudit:
        def __init__(self):
            self.calls = 0

        def record(self, event):
            self.calls += 1
            if self.calls == 3:
                raise OSError("WORM sink unavailable")

    audit = _FailOnGateAudit()
    gate = load_service("PromotionGateService")(
        evaluation_service, redteam_service, model_card_store, tracer, audit
    )
    # evaluation_service and redteam_service hold their fixture audit objects, so inject
    # the failing sink into them as well to exercise eval -> redteam -> final gate order.
    evaluation_service._audit = audit
    redteam_service._audit = audit
    with pytest.raises(AssurancePersistenceError, match="immutable gate audit"):
        gate.gate(TARGET, DATASET, CASES, actor=ACTOR)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
