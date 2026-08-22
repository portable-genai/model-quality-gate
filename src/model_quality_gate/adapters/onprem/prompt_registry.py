"""On-prem placeholder for ``PromptRegistryPort`` : the Google Distributed Cloud target.

One of the reversibility (P-02, P-12) migration placeholders: in the managed profile
this port binds to the BigQuery / GCS prompt store; switching ``profile`` to ``onprem``
rebinds it here. The adapter constructs cleanly with **no external dependencies** and
structurally satisfies the same Protocol as the managed adapter, so the contract tests
prove interface parity. Every method raises rather than silently dropping a prompt
version: prompt change-control is MRM evidence and must not be lost. Filling these bodies
in is the only change required.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import PromptVersion

_MESSAGE = (
    "On-prem PromptRegistryPort adapter is a migration placeholder; implement against "
    "your on-premise platform. Core domain logic is unchanged."
)


class OnPremPromptRegistryAdapter:
    """Placeholder prompt-registry adapter for the on-prem profile."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def put(self, version: PromptVersion) -> None:
        raise NotImplementedError(_MESSAGE)

    def get(self, name: str, version: str) -> PromptVersion | None:
        raise NotImplementedError(_MESSAGE)

    def list(self, name: str) -> list[PromptVersion]:
        raise NotImplementedError(_MESSAGE)
