"""The wire view must carry the verdicts the eval and red-team harnesses computed.

``to_jsonable`` walks ``dataclasses.fields``, and ``EvalReport.passed`` /
``RedTeamReport.passed`` are properties, so the bare walker silently dropped both. A
consumer reading them back then fell through to its own default: the static renderer
prints FAIL for an eval that cleared every threshold, and the ADK tools handed the model a
report with no verdict at all. These tests pin the derived verdicts onto the serialized
shape, so a report the harness passed can never be served as a failure again.

They also pin the boundary the fix must NOT cross: ``put_evidence`` persists through the
bare walker and ``_evidence_from_json`` rehydrates field for field, so the stored encoding
stays free of derived keys.
"""

from __future__ import annotations

from model_quality_gate.domain.models import (
    EvalMetricResult,
    EvalReport,
    EvalTarget,
    GateDecision,
    MrmEvidence,
    RedTeamCase,
    RedTeamCategory,
    RedTeamReport,
    RedTeamResult,
)
from model_quality_gate.domain.serialization import (
    eval_report_jsonable,
    gate_decision_jsonable,
    mrm_evidence_jsonable,
    redteam_report_jsonable,
    to_jsonable,
)

TARGET = EvalTarget(
    model="gemini-3.5-flash",
    prompt_version="v3",
    dataset_id="compliance-qa-golden",
    system="C1",
)


def _eval_report(*, clearing: bool = True) -> EvalReport:
    """An eval over three examples whose single metric clears its threshold or does not."""
    score = 0.94 if clearing else 0.61
    return EvalReport(
        target=TARGET,
        results=(
            EvalMetricResult(metric="groundedness", score=score, threshold=0.80, passed=clearing),
        ),
        n_examples=3,
        run_id="run-1",
    )


def _redteam_report(*, safe: bool = True) -> RedTeamReport:
    case = RedTeamCase(id="probe-1", category=RedTeamCategory.JAILBREAK, probe="ignore all rules")
    return RedTeamReport(
        target=TARGET,
        results=(RedTeamResult(case=case, blocked=safe, detail="refused", passed=safe),),
    )


def test_bare_walker_drops_both_report_verdicts() -> None:
    """Characterizes the defect this module exists to correct."""
    report = _eval_report()
    assert report.passed is True
    assert "passed" not in to_jsonable(report)

    redteam = _redteam_report()
    assert redteam.passed is True
    assert "passed" not in to_jsonable(redteam)


def test_eval_report_jsonable_carries_the_harness_verdict() -> None:
    data = eval_report_jsonable(_eval_report())

    assert data["passed"] is True
    # Plain fields keep the shape the console's EvalReport mirror expects.
    assert data["n_examples"] == 3
    assert data["run_id"] == "run-1"
    assert data["results"][0]["metric"] == "groundedness"
    assert data["results"][0]["passed"] is True


def test_eval_report_jsonable_carries_a_failing_verdict() -> None:
    data = eval_report_jsonable(_eval_report(clearing=False))

    assert data["passed"] is False


def test_eval_report_jsonable_reports_an_empty_dataset_as_failing() -> None:
    """``passed`` requires a non-empty dataset; an empty run must not serialize as a pass."""
    empty = EvalReport(target=TARGET, results=(), n_examples=0)

    assert eval_report_jsonable(empty)["passed"] is False


def test_redteam_report_jsonable_carries_the_harness_verdict() -> None:
    assert redteam_report_jsonable(_redteam_report())["passed"] is True
    assert redteam_report_jsonable(_redteam_report(safe=False))["passed"] is False


def test_gate_decision_jsonable_carries_both_sub_report_verdicts() -> None:
    """The regression: a denial must still show which of its two inputs passed."""
    decision = GateDecision(
        target=TARGET,
        eval_report=_eval_report(),
        redteam_report=_redteam_report(),
        passed=False,
        model_card_ref="gemini-3.5-flash@v3",
        mrm_evidence_ref="/v1/mrm-evidence/run-1",
        requires_human_review=True,
        caveats=("local evaluator is not attested",),
    )
    data = gate_decision_jsonable(decision)

    assert data["passed"] is False
    assert data["eval_report"]["passed"] is True
    assert data["redteam_report"]["passed"] is True
    # The renderer derives its "LOCAL QUALITY PASS" banner from exactly these two.
    assert data["caveats"] == ["local evaluator is not attested"]
    assert data["mrm_evidence_ref"] == "/v1/mrm-evidence/run-1"


def test_mrm_evidence_jsonable_carries_both_sub_report_verdicts() -> None:
    evidence = MrmEvidence(
        run_id="run-1",
        target=TARGET,
        eval_report=_eval_report(),
        redteam_report=_redteam_report(),
        passed=False,
        requires_human_review=True,
        caveats=(),
        model_card_ref="gemini-3.5-flash@v3",
        audit_event_id="evt-1",
        threshold_policy_digest="sha256:abc",
    )
    data = mrm_evidence_jsonable(evidence)

    assert data["eval_report"]["passed"] is True
    assert data["redteam_report"]["passed"] is True


def test_persisted_encoding_stays_free_of_derived_keys() -> None:
    """``put_evidence`` round-trips through the bare walker; extra keys would break it.

    ``_evidence_from_json`` rebuilds each nested report field for field, so the storage
    encoding must remain the plain field walk. This pins the wrapper to the wire.
    """
    evidence = MrmEvidence(
        run_id="run-1",
        target=TARGET,
        eval_report=_eval_report(),
        redteam_report=_redteam_report(),
        passed=True,
        requires_human_review=False,
        caveats=(),
        model_card_ref="gemini-3.5-flash@v3",
        audit_event_id="evt-1",
        threshold_policy_digest="sha256:abc",
    )
    stored = to_jsonable(evidence)

    assert "passed" not in stored["eval_report"]
    assert "passed" not in stored["redteam_report"]
