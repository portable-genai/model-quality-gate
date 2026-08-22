"""On-prem placeholder for ``ToolCatalogPort`` : the Google Distributed Cloud target.

One of the reversibility (P-02, P-12) migration placeholders: in the managed profile
this port binds to the governed MCP tool catalog; switching ``profile`` to ``onprem``
rebinds it here. The adapter constructs cleanly with **no external dependencies** and
structurally satisfies the same Protocol as the managed adapter, so the contract tests
prove interface parity. Both methods raise rather than returning a fabricated catalog:
the governed tool surface is least-privilege evidence and must be real. Filling these
bodies in is the only change required.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import ToolSpec

_MESSAGE = (
    "On-prem ToolCatalogPort adapter is a migration placeholder; implement against your "
    "on-premise platform. Core domain logic is unchanged."
)


class OnPremToolCatalogAdapter:
    """Placeholder tool-catalog adapter for the on-prem profile."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def list_tools(self) -> list[ToolSpec]:
        raise NotImplementedError(_MESSAGE)

    def get_tool(self, name: str) -> ToolSpec | None:
        raise NotImplementedError(_MESSAGE)
