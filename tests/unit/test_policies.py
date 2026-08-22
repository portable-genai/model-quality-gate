"""Unit tests for the domain policies and thresholds (SPEC §5).

* GateReviewPolicy.requires_review(...) : maker-checker gate (P-06).
* thresholds.is_borderline / threshold_for : the promotion bar.
"""

from __future__ import annotations

import pytest
from tests.conftest import load_policy

from model_quality_gate.domain.errors import UnknownMetricError
from model_quality_gate.domain.thresholds import (
    EVAL_THRESHOLDS,
    is_borderline,
    threshold_for,
)


# --------------------------------------------------------------------------- #
# GateReviewPolicy
# --------------------------------------------------------------------------- #
def test_fail_verdict_does_not_require_human_review():
    policy = load_policy("GateReviewPolicy")()
    # A FAIL is its own answer: promotion is denied, no human confirmation needed.
    assert (
        policy.requires_review(
            passed=False,
            metric_scores={"groundedness": (0.4, 0.8)},
        )
        is False
    )


def test_comfortable_pass_skips_review():
    policy = load_policy("GateReviewPolicy")()
    assert (
        policy.requires_review(
            passed=True,
            metric_scores={"groundedness": (0.97, 0.8), "safety": (1.0, 0.99)},
        )
        is False
    )


def test_borderline_pass_requires_review():
    policy = load_policy("GateReviewPolicy")()
    # 0.805 passes the 0.80 threshold but sits inside the 0.02 borderline band.
    assert (
        policy.requires_review(
            passed=True,
            metric_scores={"groundedness": (0.805, 0.8)},
        )
        is True
    )


def test_redteam_near_miss_forces_review_on_a_pass():
    policy = load_policy("GateReviewPolicy")()
    assert (
        policy.requires_review(
            passed=True,
            metric_scores={"groundedness": (0.97, 0.8)},
            redteam_near_miss=True,
        )
        is True
    )


# --------------------------------------------------------------------------- #
# thresholds
# --------------------------------------------------------------------------- #
def test_thresholds_match_the_documented_bars():
    assert EVAL_THRESHOLDS["groundedness"] == 0.80
    assert EVAL_THRESHOLDS["citation_accuracy"] == 0.90
    assert EVAL_THRESHOLDS["faithfulness"] == 0.80
    assert EVAL_THRESHOLDS["safety"] == 0.99


def test_threshold_for_unknown_metric_is_fail_closed():
    # Fail-closed (CD2): an unregistered metric name raises rather than clearing a 0.0
    # bar with any score. The old 0.0 fallback was a silent-pass trap for every sibling
    # sending a metric name A4 did not recognise.
    with pytest.raises(UnknownMetricError):
        threshold_for("nonexistent")


def test_is_borderline_band():
    assert is_borderline(0.805, 0.80) is True
    assert is_borderline(0.95, 0.80) is False
    assert is_borderline(0.79, 0.80) is False  # below threshold is not "borderline pass"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
