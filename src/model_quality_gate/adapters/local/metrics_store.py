"""Local metrics / drift store adapter (MetricsStorePort) : SQLite store.

The ``local`` profile's stand-in for the **BigQuery metrics / drift store**: a SQLite
table that records every eval report and computes per-metric drift (latest score versus
the mean baseline) for the model-risk dashboards, seedable and deterministic. SDK-free
and unconditional.

Default DB path is under a per-package local dir (``~/.model_quality_gate/metrics.db``); tests
pass ``:memory:`` for an ephemeral, deterministic store.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from ...config import Settings
from ...domain.models import DriftSignal, EvalReport, utcnow

# Drift status bands (absolute drift magnitude); mirrors the BigQuery adapter.
_WARNING_BAND = 0.05
_ALERT_BAND = 0.10

_DEFAULT_DB_DIR = Path.home() / ".model_quality_gate"
_DEFAULT_METRICS_PATH = _DEFAULT_DB_DIR / "metrics.db"


class LocalMetricsStoreAdapter:
    """SQLite metrics store: record eval reports and compute model drift offline."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        path = getattr(getattr(settings, "local", None), "metrics_path", "") or str(
            _DEFAULT_METRICS_PATH
        )
        if path not in (":memory:", "") and not path.startswith("file:"):
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        # ``check_same_thread=False`` + a lock keeps the single process-wide connection
        # (deps.get_container is lru_cached) usable from Starlette's sync-endpoint worker
        # threadpool: record()/drift() may run on a worker thread other than the one that
        # opened the connection. The lock serialises that access (single-writer).
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS eval_metrics (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                model TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                dataset_id TEXT NOT NULL,
                run_id TEXT NOT NULL DEFAULT '',
                dataset_version TEXT NOT NULL DEFAULT 'v1',
                dataset_digest TEXT NOT NULL DEFAULT '',
                evaluator TEXT NOT NULL DEFAULT '',
                attested INTEGER NOT NULL DEFAULT 0,
                schema_version TEXT NOT NULL DEFAULT 'eval-run/v1',
                artifact_refs TEXT NOT NULL DEFAULT '[]',
                example_evidence TEXT NOT NULL DEFAULT '[]',
                metric TEXT NOT NULL,
                score REAL NOT NULL,
                threshold REAL NOT NULL,
                passed INTEGER NOT NULL,
                n_examples INTEGER NOT NULL,
                recorded_at TEXT NOT NULL
            )
            """
        )
        existing = {
            str(row["name"])
            for row in self._conn.execute("PRAGMA table_info(eval_metrics)").fetchall()
        }
        migrations = {
            "run_id": "TEXT NOT NULL DEFAULT ''",
            "dataset_version": "TEXT NOT NULL DEFAULT 'v1'",
            "dataset_digest": "TEXT NOT NULL DEFAULT ''",
            "evaluator": "TEXT NOT NULL DEFAULT ''",
            "attested": "INTEGER NOT NULL DEFAULT 0",
            "schema_version": "TEXT NOT NULL DEFAULT 'eval-run/v1'",
            "artifact_refs": "TEXT NOT NULL DEFAULT '[]'",
            "example_evidence": "TEXT NOT NULL DEFAULT '[]'",
        }
        for column, definition in migrations.items():
            if column not in existing:
                self._conn.execute(f"ALTER TABLE eval_metrics ADD COLUMN {column} {definition}")
        self._conn.commit()

    def record(self, report: EvalReport) -> None:
        recorded_at = utcnow().isoformat()
        rows = [
            (
                report.target.model,
                report.target.prompt_version,
                report.target.dataset_id,
                report.run_id,
                report.dataset_version,
                report.dataset_digest,
                report.evaluator,
                1 if report.attested else 0,
                report.schema_version,
                json.dumps(list(report.artifact_refs), sort_keys=True),
                json.dumps(
                    [
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
                    sort_keys=True,
                ),
                r.metric,
                r.score,
                r.threshold,
                1 if r.passed else 0,
                report.n_examples,
                recorded_at,
            )
            for r in report.results
        ]
        with self._lock:
            self._conn.executemany(
                "INSERT INTO eval_metrics "
                "(model, prompt_version, dataset_id, run_id, dataset_version, "
                "dataset_digest, evaluator, attested, schema_version, artifact_refs, "
                "example_evidence, metric, score, threshold, passed, n_examples, "
                "recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            self._conn.commit()

    def drift(self, model: str) -> list[DriftSignal]:
        # Compare each metric's latest score against its mean baseline for the model.
        with self._lock:
            rows = self._conn.execute(
                "SELECT metric, score, recorded_at, seq FROM eval_metrics "
                "WHERE model = ? ORDER BY seq ASC",
                (model,),
            ).fetchall()
        by_metric: dict[str, list[float]] = {}
        for row in rows:
            by_metric.setdefault(row["metric"], []).append(float(row["score"]))
        signals: list[DriftSignal] = []
        for metric, scores in by_metric.items():
            baseline = sum(scores) / len(scores)
            current = scores[-1]
            signals.append(_drift_signal(model, metric, baseline, current))
        return signals


def _drift_signal(model: str, metric: str, baseline: float, current: float) -> DriftSignal:
    drift = round(current - baseline, 4)
    magnitude = abs(drift)
    if magnitude >= _ALERT_BAND:
        status = "alert"
    elif magnitude >= _WARNING_BAND:
        status = "warning"
    else:
        status = "stable"
    return DriftSignal(
        model=model,
        metric=metric,
        baseline=round(baseline, 4),
        current=round(current, 4),
        drift=drift,
        status=status,
    )
