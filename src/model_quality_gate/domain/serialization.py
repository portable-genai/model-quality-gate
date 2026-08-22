"""JSON-safe serialization for domain objects.

``to_jsonable(obj)`` converts dataclasses, enums, datetimes and nested containers into
plain JSON-serializable Python. Used by the platform HTTP clients and the audit sink.

**Sourced from the shared ``hex-service-kit`` commons.** The walker used
to live here as a copy; it is now re-exported from :mod:`hex_service_kit.serialization`
(same rules: enum ``.value``, ISO datetimes, dataclass field dicts, tuples to lists,
stringified keys, never raises). Pure standard library.

**Derived verdicts.** ``to_jsonable`` walks ``dataclasses.fields``, so a value computed by
a ``@property`` never reaches the wire. Two of A4's three verdicts are computed that way:
:attr:`~model_quality_gate.domain.models.EvalReport.passed` (every metric at or above its
threshold, over a non-empty dataset) and
:attr:`~model_quality_gate.domain.models.RedTeamReport.passed` (every probe handled safely). Only
:attr:`~model_quality_gate.domain.models.GateDecision.passed` is a stored field. Serializing a
report with the bare walker therefore drops exactly the figure the harness decided, and a
consumer reading it back falls through to its own default: the static renderer prints FAIL
for an eval that passed every metric, and the ADK tools hand the model a report with no
verdict in it at all.

Use :func:`eval_report_jsonable` / :func:`redteam_report_jsonable` /
:func:`gate_decision_jsonable` / :func:`mrm_evidence_jsonable` on every wire and rendering
path, so a served verdict is the harness's verdict and never a reader's default. The bare
walker stays untouched: it is the audit and persistence encoding, and
``ModelCardStore.put_evidence`` round-trips through it, so extra keys must not appear
there.
"""

from __future__ import annotations

from typing import Any

from hex_service_kit.serialization import to_jsonable

from .models import EvalReport, GateDecision, MrmEvidence, RedTeamReport

__all__ = [
    "eval_report_jsonable",
    "gate_decision_jsonable",
    "mrm_evidence_jsonable",
    "redteam_report_jsonable",
    "to_jsonable",
]


def eval_report_jsonable(report: EvalReport) -> dict[str, Any]:
    """One :class:`EvalReport` as JSON, carrying the verdict the evaluator computed."""
    data: dict[str, Any] = to_jsonable(report)
    data["passed"] = report.passed
    return data


def redteam_report_jsonable(report: RedTeamReport) -> dict[str, Any]:
    """One :class:`RedTeamReport` as JSON, carrying the verdict the harness computed."""
    data: dict[str, Any] = to_jsonable(report)
    data["passed"] = report.passed
    return data


def gate_decision_jsonable(decision: GateDecision) -> dict[str, Any]:
    """One :class:`GateDecision` as JSON, with both sub-report verdicts intact.

    ``decision["passed"]`` is a stored field and always survived the walk; the two reports
    it was derived from did not, so a reader could see a denial with no reason under it.
    """
    data: dict[str, Any] = to_jsonable(decision)
    data["eval_report"] = eval_report_jsonable(decision.eval_report)
    data["redteam_report"] = redteam_report_jsonable(decision.redteam_report)
    return data


def mrm_evidence_jsonable(evidence: MrmEvidence) -> dict[str, Any]:
    """One :class:`MrmEvidence` as JSON, with both sub-report verdicts intact.

    This is the independent-verification view served by ``GET /v1/mrm-evidence/{run_id}``.
    It is NOT the persisted encoding: ``ModelCardStore.put_evidence`` keeps using the bare
    walker so ``_evidence_from_json`` can rehydrate the record field for field.
    """
    data: dict[str, Any] = to_jsonable(evidence)
    data["eval_report"] = eval_report_jsonable(evidence.eval_report)
    data["redteam_report"] = redteam_report_jsonable(evidence.redteam_report)
    return data
