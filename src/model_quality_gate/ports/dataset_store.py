"""Dataset-store port : ingest and resolve golden evaluation datasets (WP-C).

Primary GCP adapter: a **CMEK Cloud Storage** golden-dataset bucket. Before this port a
golden set could only be a JSONL file bundled in the repo; the store lets a caller
publish a set (``POST /v1/datasets``) so a target can be scored against it. The stored
payload is the raw JSONL bytes exactly as uploaded; parsing into an ``EvalDataset`` stays
in ``pipelines/datasets`` so the store is format-agnostic.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class DatasetStorePort(Protocol):
    def put(self, dataset_id: str, jsonl: bytes) -> None:
        """Store (or replace) the golden dataset ``dataset_id`` as raw JSONL bytes."""
        ...

    def get(self, dataset_id: str) -> bytes | None:
        """Return the stored JSONL bytes for ``dataset_id``, or ``None`` if absent."""
        ...

    def list(self) -> list[str]:
        """Return the ids of every stored dataset."""
        ...
