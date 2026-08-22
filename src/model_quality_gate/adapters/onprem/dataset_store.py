"""On-prem placeholder for ``DatasetStorePort`` : the Google Distributed Cloud target.

A reversibility (P-02, P-12) migration placeholder: in the managed profile this port
binds to the CMEK Cloud Storage golden bucket; switching ``profile`` to ``onprem``
rebinds it here. The adapter constructs cleanly with no external dependencies and
structurally satisfies the same Protocol, so the contract tests prove interface parity.
Every method raises rather than silently dropping a golden set: an evaluation dataset is
model-risk evidence and must not be lost. Filling these bodies in is the only change
required.
"""

from __future__ import annotations

from ...config import Settings

_MESSAGE = (
    "On-prem DatasetStorePort adapter is a migration placeholder; implement against your "
    "on-premise object store. Core domain logic is unchanged."
)


class OnPremDatasetStoreAdapter:
    """Placeholder dataset-store adapter for the on-prem profile."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def put(self, dataset_id: str, jsonl: bytes) -> None:
        raise NotImplementedError(_MESSAGE)

    def get(self, dataset_id: str) -> bytes | None:
        raise NotImplementedError(_MESSAGE)

    def list(self) -> list[str]:
        raise NotImplementedError(_MESSAGE)
