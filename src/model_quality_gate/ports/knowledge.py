"""KnowledgeBaseClientPort : grounded reference retrieval from the A2 Enterprise KB.

For grounded evaluation A4 needs the reference context a golden input *should* have been
answered from. That context comes from the A2 Enterprise Knowledge Base
(``enterprise-knowledge-base``) over its ``/v1/search`` HTTP contract. The primary
adapter is therefore a **platform** HTTP client; on-prem migration swaps it for a
placeholder with no change to callers.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import Citation


@runtime_checkable
class KnowledgeBaseClientPort(Protocol):
    def retrieve(self, query: str, top_k: int = 5) -> list[Citation]:
        """Return reference citations (passages) for ``query`` from the A2 KB."""
        ...
