"""Remote-platform knowledge-base adapter : thin HTTP client to A2.

For grounded evaluation A4 retrieves the reference context a golden input should have
been answered from. That context comes from the A2 Enterprise Knowledge Base
(``enterprise-knowledge-base``) over its ``/v1/search`` contract (SPEC §6):

    POST /v1/search {query, top_k, acl_principals[], filters}
      -> {passages: [{text, citation, score, acl_tags}]}

This adapter implements :class:`KnowledgeBaseClientPort` by POSTing the query and mapping
each returned passage to a domain :class:`Citation`. The base URL is read from
``HRZ_KB_URL`` with a localhost default. A4 evaluates models, not customer data, so no PII
crosses this boundary.
"""

from __future__ import annotations

from typing import Any

import httpx

from ...domain.errors import AiQualityError
from ...domain.models import Citation
from . import _s2s

_DEFAULT_URL = "http://localhost:8082"
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class RemoteKnowledgeBaseError(AiQualityError):
    """Raised when the remote A2 knowledge-base service returns a non-2xx response."""


class RemoteKnowledgeBaseAdapter:
    """HTTP client for the A2 ``enterprise-knowledge-base`` search endpoint."""

    def __init__(self, settings: object) -> None:
        self._settings = settings
        self._base_url = _s2s.env_url("HRZ_KB_URL", _DEFAULT_URL, service="knowledge base")

    def retrieve(self, query: str, top_k: int = 5) -> list[Citation]:
        """Return reference citations for ``query`` from the A2 KB."""
        payload: dict[str, Any] = {
            "query": query,
            "top_k": top_k,
            "acl_principals": [],
            "filters": {},
        }
        url = f"{self._base_url}/v1/search"
        try:
            response = httpx.post(
                url,
                json=payload,
                timeout=_TIMEOUT,
                headers=_s2s.headers(settings=self._settings, base_url=self._base_url),
            )
        except httpx.HTTPError as exc:  # network / connection / timeout
            raise RemoteKnowledgeBaseError(f"A2 search request to {url} failed: {exc}") from exc
        if response.status_code // 100 != 2:
            raise RemoteKnowledgeBaseError(
                f"A2 search {url} returned {response.status_code}: {response.text[:500]}"
            )
        return _parse_passages(response.json())


def _parse_passages(body: dict[str, Any]) -> list[Citation]:
    out: list[Citation] = []
    for passage in body.get("passages") or ():
        citation = passage.get("citation") or {}
        out.append(
            Citation(
                source_id=str(citation.get("source_id", citation.get("id", ""))),
                title=str(citation.get("title", "")),
                url=str(citation.get("url", "")),
                page=citation.get("page"),
                snippet=str(passage.get("text", citation.get("snippet", ""))),
                score=passage.get("score"),
                acl_tags=tuple(str(t) for t in (passage.get("acl_tags") or ())),
            )
        )
    return out
