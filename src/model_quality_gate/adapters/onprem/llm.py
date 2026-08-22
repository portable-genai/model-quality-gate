"""On-prem placeholder for ``LLMPort`` : the Google Distributed Cloud target.

One of the reversibility (P-02, P-12) migration placeholders: in the managed profile
this port binds to the Gemini judge-model adapter; switching ``profile`` to ``onprem``
rebinds it here. The adapter constructs cleanly with **no external dependencies** and
structurally satisfies the same Protocol as the managed adapter. Both methods raise: an
unimplemented judge model must not silently return a default grade. Filling these bodies
in (against an on-premise model endpoint) is the only change required.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import LlmRequest, LlmResponse

_MESSAGE = (
    "On-prem LLMPort adapter is a migration placeholder; implement against your "
    "on-premise model endpoint. Core domain logic is unchanged."
)


class OnPremLLMAdapter:
    """Placeholder judge-model adapter for the on-prem profile."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def generate(self, request: LlmRequest) -> LlmResponse:
        raise NotImplementedError(_MESSAGE)

    def classify(self, text: str, labels: list[str]) -> str:
        raise NotImplementedError(_MESSAGE)
