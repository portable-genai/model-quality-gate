"""On-prem placeholder for ``KnowledgeBaseClientPort`` : Google Distributed Cloud target.

One of the reversibility (P-02, P-12) migration placeholders: in the managed / platform
profile this port is a thin HTTP client to the A2 Enterprise Knowledge Base; switching
``profile`` to ``onprem`` rebinds it here. The adapter constructs cleanly with **no
external dependencies** and structurally satisfies the same Protocol as the managed
adapter. ``retrieve`` raises rather than returning empty reference context: a silent
empty result would make grounded evaluation vacuous (nothing to ground against), which is
worse than a clear "not wired up yet" error. Filling this body in (against an internal
enterprise search) is the only change required.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import Citation

_MESSAGE = (
    "On-prem KnowledgeBaseClientPort adapter is a migration placeholder; implement "
    "against your on-premise enterprise search. Core domain logic is unchanged."
)


class OnPremKnowledgeBaseAdapter:
    """Placeholder A2 knowledge-base client for the on-prem profile."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def retrieve(self, query: str, top_k: int = 5) -> list[Citation]:
        raise NotImplementedError(_MESSAGE)
