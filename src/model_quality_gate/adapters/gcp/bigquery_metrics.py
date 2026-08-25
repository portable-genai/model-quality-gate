"""BigQuery metrics / drift store adapter (MetricsStorePort).

Backs the domain ``MetricsStorePort`` with BigQuery tables that record every eval report
and compute per-metric drift for the model-risk dashboards (current score versus a
baseline). The ``google-cloud-bigquery`` import is lazy so the on-prem and test profiles
import without it.

The adapter owns the QUERY. The BANDS that turn a movement into ``stable`` / ``warning`` /
``alert`` are a promotion judgement and live in
:func:`model_quality_gate.domain.drift.classify_drift`, which the SQLite profile calls too,
so a re-tuned band cannot mean one thing on a laptop and another in production.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from ...domain.drift import classify_drift
from ...domain.models import DriftSignal, EvalReport, utcnow


class BigQueryMetricsStoreAdapter:
    """Record eval reports and compute model drift in BigQuery."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: Any | None = None

    def _bq(self) -> Any:
        if self._client is None:
            from google.cloud import bigquery  # lazy

            self._client = bigquery.Client(project=self._settings.project_id)
        return self._client

    @property
    def _metrics_table(self) -> str:
        bq = self._settings.bigquery
        return f"{self._settings.project_id}.{bq.dataset}.{bq.metrics_table}"

    @property
    def _drift_table(self) -> str:
        bq = self._settings.bigquery
        return f"{self._settings.project_id}.{bq.dataset}.{bq.drift_table}"

    # ------------------------------------------------------------------ #
    # MetricsStorePort
    # ------------------------------------------------------------------ #
    def record(self, report: EvalReport) -> None:
        required = {
            "run_id": report.run_id,
            "dataset_version": report.dataset_version,
            "dataset_digest": report.dataset_digest,
            "evaluator": report.evaluator,
            "schema_version": report.schema_version,
        }
        missing = [name for name, value in required.items() if not value.strip()]
        if missing:
            raise ValueError("eval-run/v1 is missing required evidence: " + ", ".join(missing))
        client = self._bq()
        recorded_at = utcnow().isoformat()
        rows = [
            {
                "model": report.target.model,
                "prompt_version": report.target.prompt_version,
                "dataset_id": report.target.dataset_id,
                "run_id": report.run_id,
                "dataset_version": report.dataset_version,
                "dataset_digest": report.dataset_digest,
                "evaluator": report.evaluator,
                "attested": report.attested,
                "schema_version": report.schema_version,
                "artifact_refs": list(report.artifact_refs),
                "example_evidence": [
                    {
                        "example_id": item.example_id,
                        "score": item.score,
                        "passed": item.passed,
                        "detail": item.detail,
                        "trace_ref": item.trace_ref,
                    }
                    for item in report.example_evidence
                    if item.metric == r.metric
                ],
                "metric": r.metric,
                "score": r.score,
                "threshold": r.threshold,
                "passed": r.passed,
                "n_examples": report.n_examples,
                "recorded_at": recorded_at,
            }
            for r in report.results
        ]
        errors = client.insert_rows_json(self._metrics_table, rows)
        if errors:  # pragma: no cover - surfaced only against a live table
            raise RuntimeError(f"BigQuery insert failed for metrics: {errors}")

    def drift(self, model: str) -> list[DriftSignal]:
        client = self._bq()
        # Compare each metric's latest score against its mean baseline for the model.
        query = (
            "SELECT metric, AVG(score) AS baseline, "
            "ARRAY_AGG(score ORDER BY recorded_at DESC LIMIT 1)[OFFSET(0)] AS current "
            f"FROM `{self._metrics_table}` WHERE model = @model GROUP BY metric"
        )
        from google.cloud import bigquery  # lazy

        job_config = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("model", "STRING", model)]
        )
        signals: list[DriftSignal] = []
        for row in client.query(query, job_config=job_config).result():
            baseline = float(row["baseline"])
            current = float(row["current"])
            signals.append(classify_drift(model, str(row["metric"]), baseline, current))
        return signals
