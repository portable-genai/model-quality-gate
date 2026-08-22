"""Human-in-the-loop (maker-checker) policy : General Principle P-06.

A4 is a *decision-support* gate, never a fully autonomous approver. P-06 (maker
checker) requires that a human model-risk officer reviews a borderline or otherwise
consequential gate verdict before a model is promoted on the back of it. This module
centralises that gate so the PromotionGateService applies identical rules and the
threshold is auditable in one place.

Policy (SPEC §5):
* A **FAIL** verdict is consequential by definition (it blocks promotion) but does not
  need a human to confirm the block : the model simply is not promoted.
* A **PASS** verdict requires review when it is *borderline*: any metric passed by less
  than ``borderline_margin`` above its threshold, so a model-risk officer signs off on
  a marginal promotion rather than letting it auto-release.
* A PASS whose red-team report contains any high/critical-severity near-miss is always
  reviewed, even when every probe was ultimately blocked.
"""

from __future__ import annotations

from dataclasses import dataclass

from .thresholds import BORDERLINE_MARGIN, is_borderline


@dataclass(frozen=True, slots=True)
class GateReviewPolicy:
    """Maker-checker gate for promotion decisions (P-06). Pure decision logic.

    Args:
        borderline_margin: a passing metric within this margin above its threshold is
            treated as borderline and forces human review. Defaults to 0.02 per SPEC §5.
    """

    borderline_margin: float = BORDERLINE_MARGIN

    def requires_review(
        self,
        *,
        passed: bool,
        metric_scores: dict[str, tuple[float, float]],
        redteam_near_miss: bool = False,
    ) -> bool:
        """Decide whether a gate verdict must be routed to a human checker.

        Args:
            passed: whether the overall gate verdict is PASS.
            metric_scores: ``{metric: (score, threshold)}`` for every eval metric.
            redteam_near_miss: True if a red-team probe was blocked only marginally.

        Returns:
            True if a human model-risk officer must review before promotion.
        """
        # A FAIL is its own answer: promotion is denied, no human confirmation needed.
        if not passed:
            return False

        # A PASS that is borderline on any metric is reviewed (maker-checker).
        for score, threshold in metric_scores.values():
            if is_borderline(score, threshold, self.borderline_margin):
                return True

        # A PASS with a marginal red-team block also gets a second pair of eyes.
        return redteam_near_miss
