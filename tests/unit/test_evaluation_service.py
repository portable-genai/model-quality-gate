"""Unit tests for EvaluationService : the SPEC §5 evaluation pipeline.

Pipeline (SPEC §5):
    empty dataset -> EmptyDatasetError
    -> warm A2 reference context -> EvaluationPort.score
    -> assemble EvalReport (per-metric score/threshold/passed) -> audit

These tests are driven by the real ``local`` adapter family (no Google Cloud SDK): the
deterministic local scorer grounds against the seeded local knowledge-base index, and the
FAIL paths use thin local subclasses (``FixedEvaluation``) rather than separate fakes.
"""

from __future__ import annotations

import pytest
from tests.conftest import FixedEvaluation, load_service
from tests.fixtures import sample_targets

from model_quality_gate.domain.errors import AssurancePersistenceError, EmptyDatasetError
from model_quality_gate.domain.models import Decision, EvalMetricResult, EvalReport

ACTOR = "mlops@bank.test"
TARGET = sample_targets.SAMPLE_TARGET
DATASET = sample_targets.SAMPLE_DATASET


def test_evaluate_returns_passing_report_for_good_scores(evaluation_service, audit, metrics_store):
    report = evaluation_service.evaluate(TARGET, DATASET, actor=ACTOR)

    assert isinstance(report, EvalReport)
    assert report.target == TARGET
    assert report.n_examples == DATASET.n_examples
    assert report.passed is True
    assert report.schema_version == "eval-run/v1"
    assert report.run_id
    assert report.dataset_version == DATASET.version
    assert report.dataset_digest == DATASET.digest
    assert report.dataset_digest.startswith("sha256:")
    assert report.evaluator
    assert report.attested is False
    # Every default metric was scored and compared to a threshold.
    metrics = {r.metric for r in report.results}
    assert {"groundedness", "citation_accuracy", "faithfulness", "safety"} <= metrics
    for r in report.results:
        assert r.passed is True
        assert r.score >= r.threshold
    assert audit.events[-1].run_id == report.run_id
    assert {item.metric for item in metrics_store.drift(TARGET.model)} >= metrics


def test_evaluate_warms_a2_reference_context(evaluation_service, knowledge_base):
    evaluation_service.evaluate(TARGET, DATASET, actor=ACTOR)
    # Grounded eval pulls reference context from A2 once per golden example.
    assert len(knowledge_base.calls) == DATASET.n_examples


def test_empty_dataset_is_a_hard_error_not_a_vacuous_pass(
    evaluation, knowledge_base, llm, tracer, audit
):
    service = load_service("EvaluationService")(evaluation, knowledge_base, llm, tracer, audit)
    with pytest.raises(EmptyDatasetError):
        service.evaluate(TARGET, sample_targets.EMPTY_DATASET, actor=ACTOR)
    # The refusal is audited as ESCALATED (a human should look at an empty golden set).
    assert any(e.decision is Decision.ESCALATED for e in audit.events)


def test_report_with_zero_examples_cannot_pass_even_with_passing_metrics():
    report = EvalReport(
        target=TARGET,
        results=(EvalMetricResult("groundedness", 1.0, 0.8, True),),
        n_examples=0,
    )

    assert report.passed is False


@pytest.mark.parametrize("invalid", [float("nan"), "nan", float("inf"), "-inf"])
def test_non_finite_backend_scores_fail_closed(
    invalid, local_settings, knowledge_base, llm, tracer, audit
):
    backend = FixedEvaluation(local_settings, overrides={"groundedness": invalid})
    service = load_service("EvaluationService")(backend, knowledge_base, llm, tracer, audit)

    report = service.evaluate(TARGET, DATASET, actor=ACTOR)

    grounded = next(item for item in report.results if item.metric == "groundedness")
    assert grounded.score == 0.0
    assert report.passed is False


def test_failing_metric_yields_failing_report(local_settings, knowledge_base, llm, tracer, audit):
    # Drive groundedness below its 0.80 threshold via a thin local scorer subclass.
    backend = FixedEvaluation(local_settings, overrides={"groundedness": 0.40})
    service = load_service("EvaluationService")(backend, knowledge_base, llm, tracer, audit)

    report = service.evaluate(TARGET, DATASET, actor=ACTOR)
    assert report.passed is False
    grounded = next(r for r in report.results if r.metric == "groundedness")
    assert grounded.passed is False
    # A failing evaluation is audited as BLOCKED (promotion would be denied).
    assert any(e.decision is Decision.BLOCKED for e in audit.events)


def test_transient_backend_fault_degrades_to_failing_report(knowledge_base, llm, tracer, audit):
    class _FaultyBackend:
        def score(self, target, dataset, metrics):
            raise RuntimeError("transient backend fault")

    service = load_service("EvaluationService")(
        _FaultyBackend(), knowledge_base, llm, tracer, audit
    )
    # A transient fault must not crash the gate: it yields a failing report.
    report = service.evaluate(TARGET, DATASET, actor=ACTOR)
    assert report.passed is False
    assert all(r.score == 0.0 for r in report.results)


def test_not_implemented_backend_propagates_for_onprem_signal(knowledge_base, llm, tracer, audit):
    class _OnPremStub:
        def score(self, target, dataset, metrics):
            raise NotImplementedError("on-prem migration target")

    service = load_service("EvaluationService")(_OnPremStub(), knowledge_base, llm, tracer, audit)
    # NotImplementedError must surface (the CLI maps it to a clean exit code 2),
    # never be disguised as a failing evaluation.
    with pytest.raises(NotImplementedError):
        service.evaluate(TARGET, DATASET, actor=ACTOR)


def test_evaluate_is_wrapped_in_a_tracer_span(evaluation_service, tracer):
    evaluation_service.evaluate(TARGET, DATASET, actor=ACTOR)
    assert "evaluation.evaluate" in tracer.spans


def test_evaluate_fails_closed_when_immutable_audit_cannot_be_written(
    evaluation, knowledge_base, llm, tracer
):
    class _FailingAudit:
        def record(self, event):
            raise OSError("WORM sink unavailable")

    service = load_service("EvaluationService")(
        evaluation, knowledge_base, llm, tracer, _FailingAudit()
    )
    with pytest.raises(AssurancePersistenceError, match="immutable audit"):
        service.evaluate(TARGET, DATASET, actor=ACTOR)


def test_evaluate_fails_closed_when_metrics_evidence_cannot_be_written(
    evaluation, knowledge_base, llm, tracer, audit
):
    class _FailingMetricsStore:
        def record(self, report):
            raise OSError("quality warehouse unavailable")

    service = load_service("EvaluationService")(
        evaluation,
        knowledge_base,
        llm,
        tracer,
        audit,
        _FailingMetricsStore(),
    )
    with pytest.raises(AssurancePersistenceError, match="metrics persistence"):
        service.evaluate(TARGET, DATASET, actor=ACTOR)


def test_custom_metric_subset_is_honoured(evaluation_service):
    report = evaluation_service.evaluate(
        TARGET, DATASET, actor=ACTOR, metrics=("groundedness", "safety")
    )
    metrics = [r.metric for r in report.results]
    assert metrics == ["groundedness", "safety"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
