"""Local LLM adapter (LLMPort) : a deterministic, schema-driven judge.

The ``local`` profile's stand-in for the **Gemini judge model**: no model, no network,
fully reproducible. It reads ``request.response_schema`` (the JSON schema the calling
judge asks for) and emits a deterministic JSON object whose keys match it, with
high-quality default grades (groundedness/faithfulness/safety supported, probes blocked)
so the offline pipeline produces a real, passing judgement. There is no Google emulator
for Gemini, so this path is unconditional.

The schema-driven ``FakeLLM`` is a real, registered adapter rather than a test fixture, so
the in-memory implementation lives once under ``adapters/local`` and drives both the offline
tests and the CLI.
"""

from __future__ import annotations

import json
from typing import Any

from ...config import Settings
from ...domain.models import LlmRequest, LlmResponse, TokenUsage


def _schema_properties(schema: dict | None) -> dict[str, Any]:
    if not schema:
        return {}
    props = schema.get("properties")
    return props if isinstance(props, dict) else {}


class LocalDeterministicLLMAdapter:
    """Deterministic judge LLM whose ``generate`` returns JSON matching the request schema.

    The body is shaped from ``request.response_schema``: the groundedness / faithfulness /
    safety judges and the red-team assessment each declare a flat object whose fields this
    adapter fills with conservative-but-passing defaults, so an offline gate run produces a
    real EvalReport / RedTeamReport rather than a placeholder.
    """

    REASONING_MODEL = "gemini-3.5-flash"
    TRIAGE_MODEL = "gemini-3.1-flash-lite"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._reasoning_model = settings.models.reasoning or self.REASONING_MODEL
        self._triage_model = settings.models.triage or self.TRIAGE_MODEL

    # ------------------------------------------------------------------ #
    # LLMPort
    # ------------------------------------------------------------------ #
    def generate(self, request: LlmRequest) -> LlmResponse:
        props = _schema_properties(request.response_schema)
        body = {name: self._field(name) for name in props} if props else {"score": 0.95}
        return LlmResponse(
            text=json.dumps(body),
            usage=TokenUsage(input_tokens=80, output_tokens=40, thinking_tokens=20),
            model=request.model or self._reasoning_model,
            web_citations=(),
            raw=body,
        )

    def classify(self, text: str, labels: list[str]) -> str:
        # Deterministic triage: first label (the judges only use this for routing).
        return labels[0] if labels else ""

    # ------------------------------------------------------------------ #
    # Schema-driven body
    # ------------------------------------------------------------------ #
    @staticmethod
    def _field(name: str) -> Any:
        return {
            "score": 0.95,
            "supported": True,
            "faithful": True,
            "safe": True,
            "blocked": True,
            "passed": True,
            "detail": "ok",
            "unsupported_claims": [],
            "contradictions": [],
            "violations": [],
        }.get(name, "")
