"""Cloud Storage model-card store adapter (ModelCardStorePort).

Backs the domain ``ModelCardStorePort`` with a CMEK-encrypted Cloud Storage bucket that
holds one JSON object per model card : the MRM (model-risk management) evidence a
regulator or model-risk committee inspects. The ``google-cloud-storage`` import is lazy
so the on-prem and test profiles import without it.
"""

from __future__ import annotations

import json
from typing import Any

from ...adapters.local.model_card_store import _evidence_from_json
from ...config import Settings
from ...domain.models import ModelCard, MrmEvidence, utcnow
from ...domain.serialization import to_jsonable


class GcsModelCardStoreAdapter:
    """Store and resolve model cards as JSON objects in Cloud Storage."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: Any | None = None

    def _bucket(self) -> Any:
        if self._client is None:
            from google.cloud import storage  # lazy

            self._client = storage.Client(project=self._settings.project_id)
        return self._client.bucket(self._settings.storage.model_cards_bucket)

    def _evidence_bucket(self) -> Any:
        if self._client is None:
            from google.cloud import storage

            self._client = storage.Client(project=self._settings.project_id)
        return self._client.bucket(self._settings.storage.mrm_evidence_bucket)

    @staticmethod
    def _blob_name(model: str, version: str) -> str:
        # Slash-separated so the bucket browses as model/version.json.
        safe_model = model.replace("/", "_")
        return f"model-cards/{safe_model}/{version}.json"

    # ------------------------------------------------------------------ #
    # ModelCardStorePort
    # ------------------------------------------------------------------ #
    def put(self, card: ModelCard) -> None:
        blob = self._bucket().blob(self._blob_name(card.model, card.version))
        blob.upload_from_string(
            json.dumps(to_jsonable(card), indent=2),
            content_type="application/json",
        )

    def put_evidence(self, evidence: MrmEvidence) -> None:
        blob = self._evidence_bucket().blob(f"mrm-evidence/{evidence.run_id}.json")
        encoded = json.dumps(to_jsonable(evidence), sort_keys=True, separators=(",", ":"))
        try:
            blob.upload_from_string(
                encoded,
                content_type="application/json",
                if_generation_match=0,
            )
        except Exception:
            if not blob.exists() or blob.download_as_text() != encoded:
                raise

    def get_evidence(self, run_id: str) -> MrmEvidence | None:
        blob = self._evidence_bucket().blob(f"mrm-evidence/{run_id}.json")
        if not blob.exists():
            return None
        return _evidence_from_json(json.loads(blob.download_as_text()))

    def get(self, model: str, version: str) -> ModelCard | None:
        blob = self._bucket().blob(self._blob_name(model, version))
        if not blob.exists():
            return None
        return _card_from_json(json.loads(blob.download_as_text()))


def _card_from_json(body: dict[str, Any]) -> ModelCard:
    created = body.get("created_at")
    return ModelCard(
        model=str(body.get("model", "")),
        version=str(body.get("version", "")),
        intended_use=str(body.get("intended_use", "")),
        metrics={str(k): float(v) for k, v in (body.get("metrics") or {}).items()},
        limitations=tuple(str(x) for x in (body.get("limitations") or ())),
        mrm_evidence_refs=tuple(str(x) for x in (body.get("mrm_evidence_refs") or ())),
        owner=str(body.get("owner", "model-risk")),
        created_at=_parse_dt(created),
    )


def _parse_dt(value: Any) -> Any:
    from datetime import datetime

    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return utcnow()
    return utcnow()
