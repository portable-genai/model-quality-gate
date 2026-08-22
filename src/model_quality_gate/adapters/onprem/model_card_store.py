"""On-prem placeholder for ``ModelCardStorePort`` : the Google Distributed Cloud target.

One of the reversibility (P-02, P-12) migration placeholders: in the managed profile
this port binds to the GCS / model-registry card store; switching ``profile`` to
``onprem`` rebinds it here. The adapter constructs cleanly with **no external
dependencies** and structurally satisfies the same Protocol as the managed adapter, so
the contract tests prove interface parity. Every method raises rather than discarding a
card: a model card is the MRM evidence a regulator inspects and must not be lost. Filling
these bodies in is the only change required.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import ModelCard, MrmEvidence

_MESSAGE = (
    "On-prem ModelCardStorePort adapter is a migration placeholder; implement against "
    "your on-premise platform. Core domain logic is unchanged."
)


class OnPremModelCardStoreAdapter:
    """Placeholder model-card-store adapter for the on-prem profile."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def put(self, card: ModelCard) -> None:
        raise NotImplementedError(_MESSAGE)

    def get(self, model: str, version: str) -> ModelCard | None:
        raise NotImplementedError(_MESSAGE)

    def put_evidence(self, evidence: MrmEvidence) -> None:
        raise NotImplementedError(_MESSAGE)

    def get_evidence(self, run_id: str) -> MrmEvidence | None:
        raise NotImplementedError(_MESSAGE)
