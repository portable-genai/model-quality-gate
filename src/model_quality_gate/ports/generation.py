"""Generation port : the LLM judge model for LLM-graded metrics.

Primary GCP adapter: Gemini models on the Gemini Enterprise Agent Platform
(``gemini-3.5-flash`` for the judge at ``thinking=high``, ``gemini-3.1-flash-lite`` for
cheap triage). The judge grades groundedness / faithfulness / safety where a metric is
LLM-scored rather than computed by the Gen AI evaluation service directly.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import LlmRequest, LlmResponse


@runtime_checkable
class LLMPort(Protocol):
    def generate(self, request: LlmRequest) -> LlmResponse:
        """Generate a completion for ``request`` using the configured judge model."""
        ...

    def classify(self, text: str, labels: list[str]) -> str:
        """Cheap single-label classification (triage/routing tier model)."""
        ...
