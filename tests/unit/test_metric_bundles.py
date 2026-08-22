"""Unit tests for the eval-contract hardening (CD2/WP-A/WP-B/WP-D).

Covers the fail-closed metric registry, the per-vertical bundles, dataset-id divergence
refusal, and the GET-gate 404 hygiene. These are the guarantees the vertical eval clients
depend on (see the shared evaluation contract).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from tests.conftest import LOOPBACK_PEER, FixedEvaluation, load_service
from tests.fixtures import sample_targets

from model_quality_gate.api import deps
from model_quality_gate.api.app import app
from model_quality_gate.config import Container, LocalSettings, Settings
from model_quality_gate.domain.errors import UnknownMetricError
from model_quality_gate.domain.thresholds import (
    EVAL_THRESHOLDS,
    METRIC_BUNDLES,
    bundle_thresholds,
    metrics_for_bundle,
    resolve_metrics,
    resolve_thresholds,
    threshold_for,
    validate_metrics,
)

ACTOR = "mlops@bank.test"
TARGET = sample_targets.SAMPLE_TARGET
DATASET = sample_targets.SAMPLE_DATASET


# --------------------------------------------------------------------------- #
# WP-A : fail-closed metric registry
# --------------------------------------------------------------------------- #
def test_threshold_for_unknown_metric_raises_not_zero():
    # The silent-pass trap: an unregistered name used to clear a 0.0 bar with any score.
    with pytest.raises(UnknownMetricError):
        threshold_for("totally_made_up_metric")


def test_validate_metrics_rejects_any_unknown_name():
    with pytest.raises(UnknownMetricError):
        validate_metrics(["groundedness", "not_a_metric"])


def test_validate_metrics_passes_known_names():
    assert validate_metrics(["groundedness", "safety"]) == ("groundedness", "safety")


# --------------------------------------------------------------------------- #
# WP-B : per-vertical bundles
# --------------------------------------------------------------------------- #
def test_every_bundle_metric_is_registered():
    # No bundle may smuggle in a metric absent from the global registry (else it would be
    # a silent pass at score time). Bundles are now {metric: threshold} maps.
    for bundle, metrics in METRIC_BUNDLES.items():
        for metric in metrics:
            assert metric in EVAL_THRESHOLDS, f"{bundle}:{metric} missing from EVAL_THRESHOLDS"


def test_safety_leak_metrics_have_the_strictest_bar():
    # Safety-LEAK metrics (names ending in "safety": safety, pii_safety, no_advice_safety,
    # review_safety) gate at 0.99 (practice E2). brand_safety_detection is a detection-rate
    # metric, not a leak gate, so it is deliberately excluded (ends in "detection").
    for bundle, metrics in METRIC_BUNDLES.items():
        for metric, threshold in metrics.items():
            if metric.endswith("safety"):
                assert threshold == 0.99, f"{bundle}:{metric} should be gated at 0.99"


def test_metrics_for_bundle_unknown_raises():
    with pytest.raises(UnknownMetricError):
        metrics_for_bundle("doc999-nonexistent")


def test_per_bundle_thresholds_can_diverge_for_the_same_metric():
    # The reason thresholds are per-bundle, not global: the compliance vertical gates
    # citation_accuracy at 0.99 while most verticals gate it at 0.90. A flat global table
    # could not represent both.
    assert bundle_thresholds("mkt6-compliance")["citation_accuracy"] == 0.99
    assert bundle_thresholds("doc1-cdd-sow")["citation_accuracy"] == 0.90
    # resolve_thresholds surfaces the per-bundle bar.
    assert resolve_thresholds("mkt6-compliance")["citation_accuracy"] == 0.99


def test_all_twelve_vertical_bundles_registered():
    for bundle in (
        "doc1-cdd-sow",
        "doc2-credit-memo",
        "doc3-cio-advisory",
        "doc4-trade-finance",
        "doc5-loan-document-intelligence",
        "doc6-complaints-review",
        "mkt1-market-intel",
        "mkt2-campaign",
        "mkt3-creative",
        "mkt4-performance",
        "mkt5-nba",
        "mkt6-compliance",
    ):
        assert len(metrics_for_bundle(bundle)) == 4


def test_resolve_metrics_precedence():
    # bundle wins over metrics wins over default (names only; bundles are now maps).
    assert resolve_metrics("doc1-cdd-sow", ["groundedness"]) == metrics_for_bundle("doc1-cdd-sow")
    assert resolve_metrics(None, ["safety"]) == ("safety",)
    assert resolve_metrics(None, None) == metrics_for_bundle("default")


def test_evaluate_honours_a_bundle_and_resolves_its_thresholds(
    local_settings, knowledge_base, llm, tracer, audit
):
    # Drive a doc1 bundle through evaluate(): risk_band_accuracy fails its 0.85 bar, and
    # each row carries the bundle metric's per-bundle threshold (not the old 0.0 silent pass).
    backend = FixedEvaluation(local_settings, overrides={"risk_band_accuracy": 0.40})
    service = load_service("EvaluationService")(backend, knowledge_base, llm, tracer, audit)

    report = service.evaluate(TARGET, DATASET, ACTOR, thresholds=bundle_thresholds("doc1-cdd-sow"))

    scored = {r.metric for r in report.results}
    assert scored == set(metrics_for_bundle("doc1-cdd-sow"))
    risk = next(r for r in report.results if r.metric == "risk_band_accuracy")
    assert risk.threshold == 0.85
    assert risk.passed is False
    assert report.passed is False
    # pii_safety (safety-class) is scored 1.0 by the local scorer and clears its 0.99 bar.
    pii = next(r for r in report.results if r.metric == "pii_safety")
    assert pii.threshold == 0.99
    assert pii.passed is True


# --------------------------------------------------------------------------- #
# WP-D : API hygiene (dataset-id divergence, GET-gate 404, unknown metric 422)
# --------------------------------------------------------------------------- #
_TARGET = {
    "model": "gemini-3.5-flash",
    "prompt_version": "v3",
    "dataset_id": "compliance-qa-golden",
}


def _local_container() -> Container:
    base = Settings.load("config/settings.yaml")
    settings = Settings(
        project_id=base.project_id,
        region=base.region,
        profile="local",
        local=LocalSettings(
            db_path=":memory:",
            audit_path=":memory:",
            registry_path=":memory:",
            model_cards_path=":memory:",
            metrics_path=":memory:",
        ),
        adapters=base.adapters,
    )
    return Container(settings)


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    container = _local_container()
    monkeypatch.setattr(deps, "get_container", lambda: container)
    yield TestClient(app, client=LOOPBACK_PEER)


def test_unknown_metric_name_is_422(client):
    resp = client.post(
        "/v1/evaluations",
        json={"target": _TARGET, "dataset_id": "compliance-qa-golden", "metrics": ["bogus_metric"]},
    )
    assert resp.status_code == 422


def test_unknown_bundle_is_422(client):
    resp = client.post(
        "/v1/evaluations",
        json={"target": _TARGET, "dataset_id": "compliance-qa-golden", "bundle": "doc999"},
    )
    assert resp.status_code == 422


def test_registered_bundle_evaluates_ok(client):
    resp = client.post(
        "/v1/evaluations",
        json={"target": _TARGET, "dataset_id": "compliance-qa-golden", "bundle": "doc1-cdd-sow"},
    )
    assert resp.status_code == 200
    metrics = {r["metric"] for r in resp.json()["results"]}
    assert metrics == set(METRIC_BUNDLES["doc1-cdd-sow"])


def test_divergent_dataset_id_is_422(client):
    diverging = dict(_TARGET, dataset_id="some-other-set")
    resp = client.post(
        "/v1/evaluations",
        json={"target": diverging, "dataset_id": "compliance-qa-golden"},
    )
    assert resp.status_code == 422


def test_get_gate_unknown_dataset_is_404_not_silent_false(client):
    resp = client.get(
        "/v1/gate",
        params={"model": "gemini-3.5-flash", "prompt_version": "v3", "dataset": "no-such-dataset"},
    )
    assert resp.status_code == 404


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
