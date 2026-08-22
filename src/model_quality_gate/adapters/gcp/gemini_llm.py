"""Gemini judge-model adapter (LLMPort).

Backs the domain ``LLMPort`` with Gemini models on the Gemini Enterprise Agent Platform
via the unified ``google-genai`` SDK (Vertex backend). Used as the **judge** for
LLM-scored metrics and for cheap triage classification. The reasoning model
(``gemini-3.5-flash``) runs at ``thinking=high`` for a careful, reproducible judgement.

The ``google-genai`` SDK import is lazy so the on-prem and test profiles import without it.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from ...domain.models import (
    LlmRequest,
    LlmResponse,
    ThinkingLevel,
    TokenUsage,
)

_THINKING_BUDGET: dict[ThinkingLevel, int] = {
    ThinkingLevel.MINIMAL: 0,
    ThinkingLevel.LOW: 1024,
    ThinkingLevel.MEDIUM: 8192,
    ThinkingLevel.HIGH: -1,  # dynamic / unbounded thinking budget
}


class GeminiLLMAdapter:
    """Gemini judge-model adapter over the unified google-genai SDK."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: Any | None = None

    def _genai(self) -> Any:
        if self._client is None:
            from google import genai  # lazy

            self._client = genai.Client(
                vertexai=True,
                project=self._settings.project_id,
                location=self._settings.region,
            )
        return self._client

    # ------------------------------------------------------------------ #
    # LLMPort
    # ------------------------------------------------------------------ #
    def generate(self, request: LlmRequest) -> LlmResponse:
        from google.genai import types  # lazy

        client = self._genai()
        model = request.model or self._settings.models.reasoning
        config = types.GenerateContentConfig(
            system_instruction=request.system_instruction,
            temperature=request.temperature,
            max_output_tokens=request.max_output_tokens,
            thinking_config=types.ThinkingConfig(
                thinking_budget=_THINKING_BUDGET.get(request.thinking, 8192)
            ),
            response_mime_type=("application/json" if request.response_schema else None),
            response_schema=request.response_schema,
        )
        contents = [m.content for m in request.messages if m.role == "user"]
        result = client.models.generate_content(model=model, contents=contents, config=config)
        return LlmResponse(
            text=getattr(result, "text", "") or "",
            usage=_usage_of(result),
            model=model,
            raw=None,
        )

    def classify(self, text: str, labels: list[str]) -> str:
        from google.genai import types  # lazy

        client = self._genai()
        prompt = f"Classify the text into exactly one label from {labels}.\n\nTEXT:\n{text}"
        result = client.models.generate_content(
            model=self._settings.models.triage,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.0),
        )
        answer = (getattr(result, "text", "") or "").strip()
        for label in labels:
            if label.lower() in answer.lower():
                return label
        return labels[0] if labels else ""


def _usage_of(result: Any) -> TokenUsage:
    meta = getattr(result, "usage_metadata", None)
    if meta is None:
        return TokenUsage()
    return TokenUsage(
        input_tokens=int(getattr(meta, "prompt_token_count", 0) or 0),
        output_tokens=int(getattr(meta, "candidates_token_count", 0) or 0),
        thinking_tokens=int(getattr(meta, "thoughts_token_count", 0) or 0),
    )
