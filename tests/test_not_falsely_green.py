"""Prove every eval metric can go RED: a degraded gate decision must score below threshold.

Hrz4 IS the promotion authority, so its own offline gate validates the gate LOGIC rather than
a model's answers: each golden scenario carries the eval scores a backend would produce and the
verdict the gate should reach. That makes falsification more important here, not less. If these
four metrics cannot fail, the service that decides whether every other system may promote is
itself unchecked.

Each scorer is imported from ``eval/run_eval.py`` and fed the same real ``GateDecision`` twice:
once against the scenario it belongs to (green) and once against a scenario mutated to carry
exactly the defect the metric exists to catch (red).
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from agent_eval_kit import assert_can_go_red
from eval.run_eval import (
    DEFAULT_DATASET,
    EVAL_THRESHOLDS,
    THRESHOLDS,
    GateScenario,
    _run_gate,
    load_scenarios,
    score_gate_accuracy,
    score_redteam_detection,
    score_safety,
    score_threshold_correctness,
)

_SCENARIOS = load_scenarios(DEFAULT_DATASET)
#: A target the gate should PASS, so accuracy and threshold correctness score a clean run.
_CLEAN = next(s for s in _SCENARIOS if s.expected_gate_pass)
#: Safety below its threshold: the gate must refuse, whatever else the scores say.
_UNSAFE = next(
    s for s in _SCENARIOS if s.eval_scores.get("safety", 1.0) < EVAL_THRESHOLDS["safety"]
)
#: An unblocked red-team probe the gate must surface.
_PROBED = next(s for s in _SCENARIOS if any(not blocked for blocked in s.redteam_outcomes.values()))


@pytest.fixture(scope="module")
def clean_decision():  # type: ignore[no-untyped-def]
    return _run_gate(_CLEAN)


def test_gate_accuracy_can_go_red(clean_decision) -> None:  # type: ignore[no-untyped-def]
    assert_can_go_red(
        lambda scenario: score_gate_accuracy(scenario, clean_decision),
        green=_CLEAN,
        red=replace(_CLEAN, expected_gate_pass=False),  # the gate's verdict now disagrees
        threshold=THRESHOLDS["gate_accuracy"],
        metric="gate_accuracy",
    )


def test_threshold_correctness_can_go_red(clean_decision) -> None:  # type: ignore[no-untyped-def]
    inverted = {
        metric: (0.0 if score >= EVAL_THRESHOLDS.get(metric, 0.0) else 1.0)
        for metric, score in _CLEAN.eval_scores.items()
    }
    assert_can_go_red(
        lambda scenario: score_threshold_correctness(scenario, clean_decision),
        green=_CLEAN,
        red=replace(_CLEAN, eval_scores=inverted),  # every pass flag now sits on the wrong side
        threshold=THRESHOLDS["threshold_correctness"],
        metric="threshold_correctness",
    )


def test_redteam_detection_can_go_red(clean_decision) -> None:  # type: ignore[no-untyped-def]
    """Red is a decision from a run where nothing was probed, scored against a probed scenario."""
    probed_decision = _run_gate(_PROBED)
    assert_can_go_red(
        lambda decision: score_redteam_detection(_PROBED, decision),
        green=probed_decision,
        red=clean_decision,  # the unblocked probe never surfaced as a failed result
        threshold=THRESHOLDS["redteam_detection"],
        metric="redteam_detection",
    )


def test_safety_can_go_red(clean_decision) -> None:  # type: ignore[no-untyped-def]
    """A target whose safety is below threshold must never be a PASS."""
    unsafe_decision = _run_gate(_UNSAFE)
    assert_can_go_red(
        lambda decision: score_safety(_UNSAFE, decision),
        green=unsafe_decision,
        red=clean_decision,  # a below-threshold safety score reported as promotable
        threshold=THRESHOLDS["safety"],
        metric="safety",
    )


def test_scenarios_cover_both_verdicts() -> None:
    """A golden set that only ever expects PASS would make gate_accuracy unfalsifiable."""
    verdicts = {s.expected_gate_pass for s in _SCENARIOS}
    assert verdicts == {True, False}, f"the golden set must contain both verdicts, got {verdicts}"


def test_every_scenario_is_a_gate_scenario() -> None:
    assert all(isinstance(s, GateScenario) for s in _SCENARIOS)
