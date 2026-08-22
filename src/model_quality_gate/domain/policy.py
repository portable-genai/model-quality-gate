"""Bank-owned promotion policy: the tunable numbers, parsed from config (practice B4).

The bars a target must clear to be promotable, and the maker-checker borderline band, are
**policy**, not engineering constants: a model-risk function retunes them under its own
governance. This module is the single seam between the reference numbers in
:mod:`model_quality_gate.domain.thresholds` and a deployment's ``policy:`` section in
``config/settings.yaml``.

Contract:

* :meth:`PromotionPolicy.reference` reproduces the in-code reference constants exactly, so
  a deployment that configures nothing behaves identically to the shipped defaults.
* :meth:`PromotionPolicy.from_policy` layers a settings mapping on top of the reference:
  a partial bundle override retunes only the metrics it names and leaves the rest alone.
* Overrides are **fail-closed**: an unknown bundle name, an unknown metric inside a known
  bundle, a non-numeric value, or a bar outside ``[0.0, 1.0]`` raises
  :class:`~model_quality_gate.domain.errors.UnknownMetricError` / ``ValueError`` at load rather
  than silently gating on a number nobody reviewed. A typo must never become a lax bar.

Pure standard library: the domain reads a plain mapping, it never imports settings.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .errors import UnknownMetricError
from .hitl import GateReviewPolicy
from .thresholds import BORDERLINE_MARGIN, METRIC_BUNDLES, threshold_for, validate_metrics


def _coerce_bar(bundle: str, metric: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"policy bar {bundle}.{metric} must be a number, got {value!r}")
    bar = float(value)
    if not 0.0 <= bar <= 1.0:
        raise ValueError(f"policy bar {bundle}.{metric} must be within [0.0, 1.0], got {bar}")
    return bar


@dataclass(frozen=True, slots=True)
class PromotionPolicy:
    """The resolved promotion policy for a deployment.

    Args:
        bundles: ``{bundle: {metric: bar}}``, the effective per-vertical bars.
        borderline_margin: how close above its bar a passing metric may sit before the
            gate forces human review (P-06).
    """

    bundles: Mapping[str, Mapping[str, float]]
    borderline_margin: float = BORDERLINE_MARGIN

    # ------------------------------------------------------------------ #
    # Construction
    # ------------------------------------------------------------------ #
    @classmethod
    def reference(cls) -> PromotionPolicy:
        """The reference policy: exactly the constants in ``domain/thresholds.py``."""
        return cls(
            bundles={name: dict(bars) for name, bars in METRIC_BUNDLES.items()},
            borderline_margin=BORDERLINE_MARGIN,
        )

    @classmethod
    def from_policy(cls, policy: Mapping[str, Any] | None) -> PromotionPolicy:
        """Build the effective policy from a settings ``policy:`` mapping.

        ``None`` or an empty mapping yields :meth:`reference`, so defaults equal the
        reference constants. Recognised keys are ``borderline_margin`` (float) and
        ``bundles`` (``{bundle: {metric: bar}}``).
        """
        reference = cls.reference()
        if not policy:
            return reference

        unknown_keys = set(policy) - {"borderline_margin", "bundles"}
        if unknown_keys:
            raise ValueError(
                "unrecognised policy key(s): " + ", ".join(sorted(unknown_keys)) + " "
                "(known: borderline_margin, bundles)"
            )

        margin = policy.get("borderline_margin", reference.borderline_margin)
        if isinstance(margin, bool) or not isinstance(margin, int | float):
            raise ValueError(f"policy.borderline_margin must be a number, got {margin!r}")
        margin = float(margin)
        if not 0.0 <= margin < 1.0:
            raise ValueError(f"policy.borderline_margin must be within [0.0, 1.0), got {margin}")

        bundles = {name: dict(bars) for name, bars in reference.bundles.items()}
        overrides = policy.get("bundles") or {}
        if not isinstance(overrides, Mapping):
            raise ValueError("policy.bundles must be a mapping of bundle -> {metric: bar}")
        for bundle, bars in overrides.items():
            if bundle not in bundles:
                known = ", ".join(sorted(bundles))
                raise UnknownMetricError(
                    f"policy.bundles names unknown bundle {bundle!r} (known: {known})"
                )
            if not isinstance(bars, Mapping):
                raise ValueError(f"policy.bundles.{bundle} must be a mapping of metric -> bar")
            for metric, value in bars.items():
                if metric not in bundles[bundle]:
                    known = ", ".join(sorted(bundles[bundle]))
                    raise UnknownMetricError(
                        f"policy.bundles.{bundle} names unknown metric {metric!r} (known: {known})"
                    )
                bundles[bundle][metric] = _coerce_bar(bundle, metric, value)

        return cls(bundles=bundles, borderline_margin=margin)

    # ------------------------------------------------------------------ #
    # Use
    # ------------------------------------------------------------------ #
    def bundle_thresholds(self, bundle: str) -> dict[str, float]:
        """Return a copy of a bundle's effective ``{metric: bar}`` map, or raise."""
        try:
            return dict(self.bundles[bundle])
        except KeyError as exc:
            known = ", ".join(sorted(self.bundles))
            raise UnknownMetricError(f"unknown metric bundle {bundle!r} (known: {known})") from exc

    def thresholds_for(
        self,
        bundle: str | None = None,
        metrics: Sequence[str] | None = None,
    ) -> dict[str, float]:
        """Resolve the ``{metric: bar}`` map for a request under this policy.

        Same precedence as :func:`model_quality_gate.domain.thresholds.resolve_thresholds` (a named
        bundle wins, then an explicit metric list, else the default bundle), but every bar
        comes from the configured policy rather than the code constant.
        """
        if bundle is not None:
            return self.bundle_thresholds(bundle)
        if metrics:
            return {m: self._global_bar(m) for m in validate_metrics(metrics)}
        return self.bundle_thresholds("default")

    def review_policy(self) -> GateReviewPolicy:
        """The maker-checker policy (P-06) carrying this deployment's borderline band."""
        return GateReviewPolicy(borderline_margin=self.borderline_margin)

    def _global_bar(self, metric: str) -> float:
        """The bundle-less bar for ``metric``: default bundle first, then first-wins.

        Mirrors the ``EVAL_THRESHOLDS`` first-wins view so a metric list resolves under the
        configured policy instead of the code constants.
        """
        default_bars = self.bundles.get("default", {})
        if metric in default_bars:
            return default_bars[metric]
        for bars in self.bundles.values():
            if metric in bars:
                return bars[metric]
        # Unknown to every configured bundle: fall back to the reference registry, which
        # raises UnknownMetricError for a name nothing knows (fail-closed).
        return threshold_for(metric)
