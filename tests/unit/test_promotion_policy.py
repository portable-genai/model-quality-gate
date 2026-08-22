"""Bank-owned promotion policy (practice B4).

The bars and the maker-checker borderline band are policy numbers a model-risk function
owns. This module proves the two halves the practice demands: the configured DEFAULTS
reproduce the reference constants exactly, and an OVERRIDE actually changes the verdict.
Fail-closed handling of a bad override is asserted too: a typo must never widen a bar.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from model_quality_gate.api import deps
from model_quality_gate.config import Settings
from model_quality_gate.domain.errors import UnknownMetricError
from model_quality_gate.domain.policy import PromotionPolicy
from model_quality_gate.domain.thresholds import BORDERLINE_MARGIN, METRIC_BUNDLES

SETTINGS_YAML = Path(__file__).resolve().parents[2] / "config" / "settings.yaml"


# --------------------------------------------------------------------------- #
# Defaults reproduce the reference constants
# --------------------------------------------------------------------------- #
def test_empty_policy_reproduces_the_reference_constants() -> None:
    policy = PromotionPolicy.from_policy(None)
    assert policy.borderline_margin == BORDERLINE_MARGIN
    assert policy.bundles == {name: dict(bars) for name, bars in METRIC_BUNDLES.items()}


def test_shipped_settings_policy_equals_the_reference_policy() -> None:
    """The committed config/settings.yaml must not silently retune a shipped bar."""
    settings = Settings.load(SETTINGS_YAML)
    configured = PromotionPolicy.from_policy(settings.policy)
    assert configured == PromotionPolicy.reference()


def test_settings_policy_section_actually_carries_the_numbers() -> None:
    """The tunable numbers must be REACHABLE from the settings file, not only in code."""
    settings = Settings.load(SETTINGS_YAML)
    assert settings.policy["borderline_margin"] == BORDERLINE_MARGIN
    assert settings.policy["bundles"]["default"]["safety"] == METRIC_BUNDLES["default"]["safety"]


# --------------------------------------------------------------------------- #
# An override changes behaviour
# --------------------------------------------------------------------------- #
def test_override_retunes_only_the_named_bar() -> None:
    policy = PromotionPolicy.from_policy(
        {"bundles": {"default": {"groundedness": 0.95}}},
    )
    bars = policy.thresholds_for()
    assert bars["groundedness"] == 0.95
    # Untouched metrics keep the reference bar.
    assert bars["citation_accuracy"] == METRIC_BUNDLES["default"]["citation_accuracy"]
    # Other bundles are untouched.
    assert policy.thresholds_for("doc2-credit-memo") == METRIC_BUNDLES["doc2-credit-memo"]


def test_override_changes_the_pass_fail_outcome() -> None:
    """The point of the knob: the same score passes under one policy and fails the other."""
    score = 0.85
    reference_bar = PromotionPolicy.reference().thresholds_for()["groundedness"]
    strict_bar = PromotionPolicy.from_policy(
        {"bundles": {"default": {"groundedness": 0.95}}},
    ).thresholds_for()["groundedness"]
    assert score >= reference_bar
    assert not score >= strict_bar


def test_borderline_margin_override_changes_the_review_policy() -> None:
    """Widening the band routes a pass to a human that the default would have released."""
    scores = {"groundedness": (0.85, 0.80)}  # 0.05 above its bar
    assert (
        not PromotionPolicy.reference()
        .review_policy()
        .requires_review(passed=True, metric_scores=scores)
    )
    widened = PromotionPolicy.from_policy({"borderline_margin": 0.10})
    assert widened.review_policy().requires_review(passed=True, metric_scores=scores)


def test_metric_list_path_uses_the_configured_bar() -> None:
    """A bundle-less metric list must resolve under the policy, not the code constant."""
    policy = PromotionPolicy.from_policy({"bundles": {"default": {"safety": 0.995}}})
    assert policy.thresholds_for(None, ["safety"]) == {"safety": 0.995}


# --------------------------------------------------------------------------- #
# Fail-closed: a bad override is a hard error, never a lax bar
# --------------------------------------------------------------------------- #
def test_unknown_bundle_in_policy_is_rejected() -> None:
    with pytest.raises(UnknownMetricError):
        PromotionPolicy.from_policy({"bundles": {"doc9-nonexistent": {"groundedness": 0.5}}})


def test_unknown_metric_in_policy_is_rejected() -> None:
    with pytest.raises(UnknownMetricError):
        PromotionPolicy.from_policy({"bundles": {"default": {"groundednes": 0.5}}})


@pytest.mark.parametrize("bad", [1.5, -0.1, "0.9", True, None])
def test_out_of_range_or_non_numeric_bar_is_rejected(bad: object) -> None:
    with pytest.raises(ValueError):
        PromotionPolicy.from_policy({"bundles": {"default": {"groundedness": bad}}})


@pytest.mark.parametrize("bad", [1.0, -0.01, "0.02"])
def test_bad_borderline_margin_is_rejected(bad: object) -> None:
    with pytest.raises(ValueError):
        PromotionPolicy.from_policy({"borderline_margin": bad})


def test_unknown_policy_key_is_rejected() -> None:
    """A misspelled section name must not be ignored into a no-op policy."""
    with pytest.raises(ValueError):
        PromotionPolicy.from_policy({"borderline_margins": 0.05})


def test_unknown_bundle_at_resolve_time_still_raises() -> None:
    with pytest.raises(UnknownMetricError):
        PromotionPolicy.reference().thresholds_for("no-such-bundle")


# --------------------------------------------------------------------------- #
# Wiring: the API and the gate service actually read the configured policy
# --------------------------------------------------------------------------- #
def test_api_resolves_thresholds_through_the_configured_policy() -> None:
    deps.get_promotion_policy.cache_clear()
    try:
        policy = deps.get_promotion_policy()
        assert policy == PromotionPolicy.reference()
    finally:
        deps.get_promotion_policy.cache_clear()


class _StubContainer:
    """Just enough of a Container for build_gate_service: every port is a sentinel."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def __getattr__(self, name: str) -> object:
        return object()


def test_gate_service_review_policy_comes_from_settings() -> None:
    """The gate's maker-checker band must follow the deployment's policy, not the constant."""
    default_service = deps.build_gate_service(_StubContainer(Settings()))
    assert default_service._review.borderline_margin == BORDERLINE_MARGIN

    widened = Settings(policy={"borderline_margin": 0.25})
    service = deps.build_gate_service(_StubContainer(widened))
    assert service._review.borderline_margin == 0.25
