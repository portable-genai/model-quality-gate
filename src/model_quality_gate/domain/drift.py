"""Drift banding and the re-gate escalation policy. Pure, deterministic, stdlib only.

Two pieces of consequential logic live here, and both used to live somewhere they could
not be replayed:

* :func:`classify_drift` turns a baseline and a current score into a banded
  :class:`~model_quality_gate.domain.models.DriftSignal`. The bands decide whether a model
  reads as ``stable``, ``warning`` or ``alert``, which is a promotion-relevant judgement,
  so it belongs in the core rather than in each metrics-store adapter.
* :class:`DriftRegatePolicy` turns those signals into a
  :class:`~model_quality_gate.domain.models.DriftEscalation`: what a human now owes the
  model. It is the drift-side twin of
  :class:`~model_quality_gate.domain.hitl.GateReviewPolicy`, and it obeys the same rule:
  **escalation only ever raises the bar.** Nothing here promotes, demotes, or re-runs the
  gate. It states a requirement; a person satisfies it.

Fail-closed in both directions that matter:

* **No signal is not a stable signal.** A model with nothing recorded against it is
  ``unmeasured``, and unmeasured escalates. A check that reports calm over zero
  observations has not observed anything.
* **A status this policy does not recognise is not a stable one.** ``status`` on a
  ``DriftSignal`` is an open ``str`` (an adapter, or a future band, may widen it), so a
  value outside the known ordering is reported as ``unrecognised`` and escalates rather
  than defaulting into the quiet end of the scale.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from .models import DriftEscalation, DriftSignal

#: Drift status bands, measured on the ABSOLUTE magnitude of ``current - baseline``. These
#: were duplicated in the BigQuery and SQLite metrics adapters; a band is a promotion
#: judgement, so it is single-homed here and both adapters call :func:`classify_drift`.
WARNING_BAND: float = 0.05
ALERT_BAND: float = 0.10

STABLE = "stable"
WARNING = "warning"
ALERT = "alert"

#: Nothing was recorded for the model, so its quality is unknown rather than calm.
UNMEASURED = "unmeasured"
#: At least one signal carried a status outside :data:`DRIFT_STATUS_ORDER`.
UNRECOGNISED = "unrecognised"

#: The recognised statuses, calmest first. Everything outside this tuple escalates.
DRIFT_STATUS_ORDER: tuple[str, ...] = (STABLE, WARNING, ALERT)

_RANK: dict[str, int] = {status: rank for rank, status in enumerate(DRIFT_STATUS_ORDER)}


def classify_drift(model: str, metric: str, baseline: float, current: float) -> DriftSignal:
    """Band one metric's movement away from its baseline into a :class:`DriftSignal`.

    Rounded to four decimal places so the same history yields byte-identical evidence on
    every profile, and banded on the absolute magnitude so an improvement large enough to
    be suspicious is surfaced alongside a regression.
    """
    drift = round(current - baseline, 4)
    magnitude = abs(drift)
    if magnitude >= ALERT_BAND:
        status = ALERT
    elif magnitude >= WARNING_BAND:
        status = WARNING
    else:
        status = STABLE
    return DriftSignal(
        model=model,
        metric=metric,
        baseline=round(baseline, 4),
        current=round(current, 4),
        drift=drift,
        status=status,
    )


@dataclass(frozen=True, slots=True)
class DriftRegatePolicy:
    """Decide what a set of drift signals requires of a human. Pure decision logic.

    Args:
        re_gate_statuses: statuses that require the target to be put back through the
            promotion gate before its last verdict may still be relied on.
        review_statuses: statuses that require a model-risk officer to look, without on
            their own demanding a full re-gate.
    """

    re_gate_statuses: frozenset[str] = field(default=frozenset({ALERT}))
    review_statuses: frozenset[str] = field(default=frozenset({WARNING, ALERT}))

    def assess(self, model: str, signals: Sequence[DriftSignal]) -> DriftEscalation:
        """Turn ``signals`` into the escalation they owe. Never promotes or demotes.

        Three fail-closed rules, in order:

        1. **no signal at all** is :data:`UNMEASURED` and escalates. Nothing was observed,
           so nothing may be reported as calm;
        2. **a status outside** :data:`DRIFT_STATUS_ORDER` is :data:`UNRECOGNISED` and
           escalates, rather than defaulting into the quiet end of an ordering it is not
           a member of;
        3. otherwise the worst recognised status decides, on a graded ladder: an
           escalating status requires a re-gate AND a review, a review-only status
           requires a review, and stable requires nothing.
        """
        ordered = tuple(signals)
        if not ordered:
            return DriftEscalation(
                model=model,
                status=UNMEASURED,
                requires_re_gate=True,
                requires_human_review=True,
                reasons=(
                    "no drift signal is recorded for this model, so its online quality is "
                    "unmeasured; an absent measurement is not a stable one",
                    _RE_GATE_LINE,
                ),
            )

        unrecognised = tuple(sorted({s.metric for s in ordered if s.status not in _RANK}))
        banded = {s.metric for s in ordered if s.status in self.re_gate_statuses}
        escalating = tuple(sorted(banded.union(unrecognised)))
        requires_re_gate = bool(escalating)
        requires_human_review = requires_re_gate or any(
            s.status in self.review_statuses for s in ordered
        )
        if unrecognised:
            status = UNRECOGNISED
        else:
            status = DRIFT_STATUS_ORDER[max(_RANK[s.status] for s in ordered)]
        return DriftEscalation(
            model=model,
            status=status,
            requires_re_gate=requires_re_gate,
            requires_human_review=requires_human_review,
            signals=ordered,
            escalating_metrics=escalating,
            reasons=_reasons(ordered, escalating, unrecognised),
        )


#: The one sentence every escalating verdict ends on, so a reader of any surface is told
#: both what is owed and, explicitly, that nothing was done about it here.
_RE_GATE_LINE = (
    "re-run the promotion gate for this model before its last verdict may still be "
    "relied on. This assessment promotes nothing and demotes nothing."
)


def _reasons(
    signals: tuple[DriftSignal, ...],
    escalating: tuple[str, ...],
    unrecognised: tuple[str, ...],
) -> tuple[str, ...]:
    """Deterministic, metric-sorted explanations for the escalation."""
    lines = [
        f"{s.metric} moved {s.drift:+.4f} from baseline {s.baseline:.4f} "
        f"to {s.current:.4f} ({s.status} band)"
        for s in sorted(signals, key=lambda s: s.metric)
    ]
    for metric in unrecognised:
        lines.append(
            f"{metric} carries drift status "
            f"{next(s.status for s in signals if s.metric == metric)!r}, which this policy "
            "does not recognise; it is escalated rather than read as stable"
        )
    if escalating:
        lines.append(f"escalating metrics: {', '.join(escalating)}")
        lines.append(_RE_GATE_LINE)
    return tuple(lines)
