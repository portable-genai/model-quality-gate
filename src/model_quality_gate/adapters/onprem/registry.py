"""On-prem placeholder for ``AgentRegistryPort`` : the Google Distributed Cloud target.

One of the reversibility (P-02, P-12) migration placeholders: in the managed / platform
profile this port publishes the A2A AgentCard to the ``agent-registry`` service;
switching ``profile`` to ``onprem`` rebinds it here. The adapter constructs cleanly with
**no external dependencies** and structurally satisfies the same Protocol as the managed
adapter, so the contract tests prove interface parity. Every method raises rather than
silently succeeding: registration (R4) is governance evidence and must not be faked.
Filling these bodies in is the only change required.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import AgentCard

_MESSAGE = (
    "On-prem AgentRegistryPort adapter is a migration placeholder; implement against "
    "your on-premise platform. Core domain logic is unchanged."
)


class OnPremRegistryAdapter:
    """Placeholder registry adapter for the on-prem (Google Distributed Cloud) profile."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def register(self, card: AgentCard) -> None:
        raise NotImplementedError(_MESSAGE)

    def get(self, name: str) -> AgentCard | None:
        raise NotImplementedError(_MESSAGE)

    def list(self) -> list[AgentCard]:
        raise NotImplementedError(_MESSAGE)
