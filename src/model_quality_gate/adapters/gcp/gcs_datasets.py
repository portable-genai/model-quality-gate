"""Cloud Storage dataset-store adapter (DatasetStorePort).

Backs the domain ``DatasetStorePort`` with the CMEK-encrypted golden-dataset bucket
(``storage.golden_bucket``), region-pinned like every other managed call. Each dataset is
one JSONL object keyed by id. The ``google-cloud-storage`` import is lazy so the on-prem
and test profiles import without it.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings


class GcsDatasetStoreAdapter:
    """Store and resolve golden JSONL datasets as objects in Cloud Storage."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: Any | None = None

    def _storage_client(self) -> Any:
        if self._client is None:
            from google.cloud import storage  # lazy

            self._client = storage.Client(project=self._settings.project_id)
        return self._client

    def _bucket(self) -> Any:
        return self._storage_client().bucket(self._settings.storage.golden_bucket)

    @staticmethod
    def _blob_name(dataset_id: str) -> str:
        safe = dataset_id.replace("/", "_")
        return f"golden-datasets/{safe}.jsonl"

    # ------------------------------------------------------------------ #
    # DatasetStorePort
    # ------------------------------------------------------------------ #
    def put(self, dataset_id: str, jsonl: bytes) -> None:
        blob = self._bucket().blob(self._blob_name(dataset_id))
        blob.upload_from_string(jsonl, content_type="application/x-ndjson")

    def get(self, dataset_id: str) -> bytes | None:
        blob = self._bucket().blob(self._blob_name(dataset_id))
        if not blob.exists():
            return None
        return bytes(blob.download_as_bytes())

    def list(self) -> list[str]:
        prefix = "golden-datasets/"
        client = self._storage_client()
        blobs = client.list_blobs(self._settings.storage.golden_bucket, prefix=prefix)
        ids: list[str] = []
        for blob in blobs:
            name = blob.name[len(prefix) :]
            if name.endswith(".jsonl"):
                ids.append(name[: -len(".jsonl")])
        return sorted(ids)
