"""Gen AI evaluation adapter : the A4 scoring backend (EvaluationPort).

Backs the domain ``EvaluationPort`` with the **Gen AI evaluation service**, accessed
through ``vertexai.Client(project, location).evals``. Over a golden dataset it scores a
target on the model-risk metrics (groundedness, citation accuracy, faithfulness, safety)
and maps the result onto a ``{metric: score}`` dict the EvaluationService turns into an
``EvalReport``.

The Vertex AI SDK import is lazy so the on-prem and test profiles import without it.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from ...domain.models import (
    EvalDataset,
    EvalExampleEvidence,
    EvalTarget,
    EvaluationOutcome,
)


class GenAiEvalAdapter:
    """Run the Gen AI evaluation service and return per-metric scores."""

    attested = True

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: Any | None = None

    # ------------------------------------------------------------------ #
    # Lazy SDK plumbing
    # ------------------------------------------------------------------ #
    def _evals(self) -> Any:
        """Return (and cache) the ``evals`` surface of the Vertex AI client."""
        if self._client is None:
            import vertexai  # lazy

            # verify: https://cloud.google.com/vertex-ai/generative-ai/docs/models/evaluation
            self._client = vertexai.Client(
                project=self._settings.project_id,
                location=self._settings.eval.location,
            )
        return self._client.evals

    # ------------------------------------------------------------------ #
    # EvaluationPort
    # ------------------------------------------------------------------ #
    def score(
        self,
        target: EvalTarget,
        dataset: EvalDataset,
        metrics: list[str],
    ) -> EvaluationOutcome:
        """Score a target and retain redacted per-example metric/verdict evidence."""
        evals = self._evals()
        metric_objs = self._metrics(metrics)
        # verify: the current SDK pattern is run_inference(...) to materialise model
        # responses over the dataset, then evaluate(...) with a metric list to score them.
        # https://cloud.google.com/vertex-ai/generative-ai/docs/models/run-evaluation
        inference = evals.run_inference(
            model=target.model or self._settings.eval.judge_model,
            src=self._dataset_src(dataset),
        )
        result = evals.evaluate(traces=inference, metrics=metric_objs)
        return EvaluationOutcome(
            scores=_extract_summary_scores(result, metrics),
            examples=_extract_example_evidence(result, metrics),
            artifact_refs=_extract_artifact_refs(result),
        )

    # ------------------------------------------------------------------ #
    # Metric construction
    # ------------------------------------------------------------------ #
    def _metrics(self, metrics: list[str]) -> list[Any]:
        """Build prebuilt metric objects, falling back to metric-name strings."""
        try:
            from vertexai import types as eval_types  # lazy
        except Exception:  # noqa: BLE001
            return list(metrics)
        # verify: prebuilt metric names —
        # https://cloud.google.com/vertex-ai/generative-ai/docs/models/metrics-templates
        prebuilt = getattr(eval_types, "PrebuiltMetric", None)
        if prebuilt is None:
            return list(metrics)
        out: list[Any] = []
        for metric in metrics:
            attr = metric.upper()
            out.append(getattr(prebuilt, attr, None) or metric)
        return out

    @staticmethod
    def _dataset_src(dataset: EvalDataset) -> list[dict[str, Any]]:
        """Project the golden examples into the eval service's row shape."""
        return [
            {
                "id": ex.id,
                "prompt": ex.input,
                "reference": " ".join(ex.expected_points),
            }
            for ex in dataset.examples
        ]


# ---------------------------------------------------------------------- #
# Pure mapping helpers (no SDK types in signatures)
# ---------------------------------------------------------------------- #
def _extract_summary_scores(result: Any, metrics: list[str]) -> dict[str, float]:
    """Normalise the eval result's summary metrics into a ``{metric: score}`` dict."""
    raw = getattr(result, "summary_metrics", None)
    if raw is None:
        raw = getattr(result, "metrics", None)
    if raw is None and isinstance(result, dict):
        raw = result.get("summary_metrics") or result.get("metrics")

    scores: dict[str, float] = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            scores[_norm_metric(key)] = _coerce_score(value)
    else:
        for entry in raw or []:
            name = getattr(entry, "name", None) or (
                entry.get("name") if isinstance(entry, dict) else None
            )
            if name is None:
                continue
            value = (
                getattr(entry, "score", None) if not isinstance(entry, dict) else entry.get("score")
            )
            scores[_norm_metric(name)] = _coerce_score(value)

    # Ensure every requested metric has an entry (0.0 if the backend omitted it).
    return {metric: scores.get(metric, 0.0) for metric in metrics}


def _norm_metric(name: str) -> str:
    key = str(name).lower()
    for suffix in ("/mean", "_mean", "/score", "_score"):
        if key.endswith(suffix):
            key = key[: -len(suffix)]
    return key


def _coerce_score(value: Any) -> float:
    if isinstance(value, dict):
        value = value.get("mean") or value.get("score") or value.get("value")
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _extract_example_evidence(result: Any, metrics: list[str]) -> tuple[EvalExampleEvidence, ...]:
    """Extract safe row-level evidence across SDK result representations.

    The managed SDK has exposed detail rows as dataframe-like ``metrics_table`` values
    and as list/dict payloads over time. Only identifiers, scores, verdict explanations,
    and trace references are retained; prompt/response columns are deliberately ignored.
    """
    raw = getattr(result, "metrics_table", None)
    if raw is None:
        raw = getattr(result, "details", None)
    if raw is None and isinstance(result, dict):
        raw = result.get("metrics_table") or result.get("details") or result.get("rows")
    rows = _rows(raw)
    evidence: list[EvalExampleEvidence] = []
    for index, row in enumerate(rows):
        example_id = str(
            row.get("id") or row.get("example_id") or row.get("eval_case_id") or f"row-{index + 1}"
        )
        trace_ref = _optional_text(
            row.get("trace_ref") or row.get("trace_id") or row.get("inference_id")
        )
        for metric in metrics:
            score = _find_metric_value(row, metric, ("", "/score", "_score"))
            if score is None:
                continue
            numeric = _coerce_score(score)
            verdict = _find_metric_value(row, metric, ("/verdict", "_verdict", "/passed"))
            passed = _coerce_verdict(verdict, numeric)
            raw_detail = _optional_text(
                _find_metric_value(
                    row,
                    metric,
                    ("/rationale", "_rationale", "/explanation", "_explanation"),
                )
            )
            # Managed rationales may quote prompts, responses, tool payloads, or PII.
            # Keep the verdict pivot here and leave content-bearing rationale in the
            # separately governed managed artifact referenced by ``artifact_refs``.
            detail = "managed-rationale-available-in-governed-artifact" if raw_detail else ""
            evidence.append(
                EvalExampleEvidence(
                    example_id=example_id,
                    metric=metric,
                    score=numeric,
                    passed=passed,
                    detail=detail,
                    trace_ref=trace_ref,
                )
            )
    return tuple(evidence)


def _rows(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if hasattr(raw, "to_dict"):
        try:
            converted = raw.to_dict(orient="records")
            if isinstance(converted, list):
                return [item for item in converted if isinstance(item, dict)]
        except TypeError:
            pass
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        records = raw.get("records") or raw.get("rows")
        if isinstance(records, list):
            return [item for item in records if isinstance(item, dict)]
    return []


def _find_metric_value(row: dict[str, Any], metric: str, suffixes: tuple[str, ...]) -> Any:
    normalized = {_norm_key(str(key)): value for key, value in row.items()}
    for suffix in suffixes:
        candidate = _norm_key(metric + suffix)
        if candidate in normalized:
            return normalized[candidate]
    return None


def _norm_key(value: str) -> str:
    return value.strip().lower().replace(" ", "_")


def _coerce_verdict(value: Any, score: float) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"pass", "passed", "true", "1"}:
        return True
    if text in {"fail", "failed", "false", "0"}:
        return False
    return score >= 0.5


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _extract_artifact_refs(result: Any) -> tuple[str, ...]:
    refs: list[str] = []
    for key in ("name", "resource_name", "evaluation_run", "evaluation_result_uri"):
        value = result.get(key) if isinstance(result, dict) else getattr(result, key, None)
        text = _optional_text(value)
        if text and text not in refs:
            refs.append(text)
    return tuple(refs)
