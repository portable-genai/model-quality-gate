"""Local model-card store adapter (ModelCardStorePort) : SQLite JSON store.

The ``local`` profile's stand-in for the **GCS / model-registry card store**: a small
SQLite table holding one JSON object per model card (the MRM evidence a model-risk
committee inspects), seedable and deterministic. SDK-free and unconditional.

Cards are serialised with the domain ``to_jsonable`` so a stored card round-trips through
JSON exactly like the managed store writes it. Default DB path is under a per-package
local dir (``~/.model_quality_gate/model_cards.db``); tests pass ``:memory:``.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from ...config import Settings
from ...domain.models import (
    EvalExampleEvidence,
    EvalMetricResult,
    EvalReport,
    EvalTarget,
    ModelCard,
    MrmEvidence,
    RedTeamCase,
    RedTeamCategory,
    RedTeamReport,
    RedTeamResult,
    utcnow,
)
from ...domain.serialization import to_jsonable

_DEFAULT_DB_DIR = Path.home() / ".model_quality_gate"
_DEFAULT_CARDS_PATH = _DEFAULT_DB_DIR / "model_cards.db"


class LocalModelCardStoreAdapter:
    """SQLite model-card store: store and resolve model cards as JSON objects."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        path = getattr(getattr(settings, "local", None), "model_cards_path", "") or str(
            _DEFAULT_CARDS_PATH
        )
        if path not in (":memory:", "") and not path.startswith("file:"):
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        # ``check_same_thread=False`` + a lock keeps the single process-wide connection
        # (deps.get_container is lru_cached) usable from Starlette's sync-endpoint worker
        # threadpool: put()/get() may run on a worker thread other than the one that opened
        # the connection. The lock serialises that access (single-writer).
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS model_cards (
                model TEXT NOT NULL,
                version TEXT NOT NULL,
                card_json TEXT NOT NULL,
                PRIMARY KEY (model, version)
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mrm_evidence (
                run_id TEXT PRIMARY KEY,
                evidence_json TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def put(self, card: ModelCard) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO model_cards (model, version, card_json) VALUES (?, ?, ?) "
                "ON CONFLICT(model, version) DO UPDATE SET card_json=excluded.card_json",
                (card.model, card.version, json.dumps(to_jsonable(card))),
            )
            self._conn.commit()

    def get(self, model: str, version: str) -> ModelCard | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT card_json FROM model_cards WHERE model = ? AND version = ?",
                (model, version),
            ).fetchone()
        return self._card_from_json(json.loads(row["card_json"])) if row else None

    def put_evidence(self, evidence: MrmEvidence) -> None:
        """Append one immutable run artifact; conflicting rewrites fail closed."""
        encoded = json.dumps(to_jsonable(evidence), sort_keys=True, separators=(",", ":"))
        with self._lock:
            existing = self._conn.execute(
                "SELECT evidence_json FROM mrm_evidence WHERE run_id = ?", (evidence.run_id,)
            ).fetchone()
            if existing:
                if existing["evidence_json"] != encoded:
                    raise ValueError(f"MRM run {evidence.run_id!r} already has different evidence")
                return
            self._conn.execute(
                "INSERT INTO mrm_evidence (run_id, evidence_json) VALUES (?, ?)",
                (evidence.run_id, encoded),
            )
            self._conn.commit()

    def get_evidence(self, run_id: str) -> MrmEvidence | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT evidence_json FROM mrm_evidence WHERE run_id = ?", (run_id,)
            ).fetchone()
        return _evidence_from_json(json.loads(row["evidence_json"])) if row else None

    @staticmethod
    def _card_from_json(body: dict[str, Any]) -> ModelCard:
        created = body.get("created_at")
        try:
            created_at = datetime.fromisoformat(created) if isinstance(created, str) else utcnow()
        except ValueError:
            created_at = utcnow()
        return ModelCard(
            model=str(body.get("model", "")),
            version=str(body.get("version", "")),
            intended_use=str(body.get("intended_use", "")),
            metrics={str(k): float(v) for k, v in (body.get("metrics") or {}).items()},
            limitations=tuple(str(x) for x in (body.get("limitations") or ())),
            mrm_evidence_refs=tuple(str(x) for x in (body.get("mrm_evidence_refs") or ())),
            owner=str(body.get("owner", "model-risk")),
            created_at=created_at,
        )


def _evidence_from_json(body: dict[str, Any]) -> MrmEvidence:
    target_body = body["target"]
    target = EvalTarget(**target_body)
    eval_body = body["eval_report"]
    eval_report = EvalReport(
        target=target,
        results=tuple(EvalMetricResult(**item) for item in eval_body["results"]),
        example_evidence=tuple(
            EvalExampleEvidence(
                example_id=item["example_id"],
                metric=item["metric"],
                score=float(item["score"]),
                passed=bool(item["passed"]),
                detail=item.get("detail", ""),
                trace_ref=item.get("trace_ref"),
            )
            for item in eval_body.get("example_evidence", ())
        ),
        n_examples=int(eval_body.get("n_examples", 0)),
        run_id=eval_body.get("run_id", ""),
        dataset_version=eval_body.get("dataset_version", ""),
        dataset_digest=eval_body.get("dataset_digest", ""),
        evaluator=eval_body.get("evaluator", ""),
        trace_id=eval_body.get("trace_id"),
        correlation_id=eval_body.get("correlation_id"),
        artifact_refs=tuple(eval_body.get("artifact_refs", ())),
        attested=bool(eval_body.get("attested", False)),
        schema_version=eval_body.get("schema_version", "eval-run/v1"),
    )
    red_body = body["redteam_report"]
    redteam_report = RedTeamReport(
        target=target,
        results=tuple(
            RedTeamResult(
                case=RedTeamCase(
                    id=item["case"]["id"],
                    category=RedTeamCategory(item["case"]["category"]),
                    probe=item["case"]["probe"],
                    expected_block=bool(item["case"].get("expected_block", True)),
                ),
                blocked=bool(item["blocked"]),
                detail=item.get("detail", ""),
                passed=bool(item["passed"]),
            )
            for item in red_body["results"]
        ),
    )
    return MrmEvidence(
        run_id=body["run_id"],
        target=target,
        eval_report=eval_report,
        redteam_report=redteam_report,
        passed=bool(body["passed"]),
        requires_human_review=bool(body["requires_human_review"]),
        caveats=tuple(body.get("caveats", ())),
        model_card_ref=body["model_card_ref"],
        audit_event_id=body["audit_event_id"],
        threshold_policy_digest=body["threshold_policy_digest"],
        created_at=_parse_dt(body.get("created_at")),
        schema_version=body.get("schema_version", "mrm-evidence/v1"),
    )


def _parse_dt(value: Any) -> datetime:
    try:
        return datetime.fromisoformat(value) if isinstance(value, str) else utcnow()
    except ValueError:
        return utcnow()
