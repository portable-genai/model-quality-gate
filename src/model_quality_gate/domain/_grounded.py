"""Shared judge / parsing helpers (private to the domain layer).

A4's evaluation and red-team services share the same machinery: render reference
passages into a judge prompt, call the judge LLM with a structured-output schema,
defensively parse the JSON reply, and coerce model-emitted values. This module factors
out that core so each service keeps the exact constructor and method signature mandated
by SPEC §5 while sharing one well-tested skeleton. It is ``_``-prefixed and not part of
the public domain API.

Pure domain code : talks only to ports and models, no Google Cloud / ADK imports.
"""

from __future__ import annotations

import json
import math
from typing import Any

from .models import (
    Citation,
    LlmMessage,
    LlmRequest,
    LlmResponse,
    ThinkingLevel,
)
from .prompts import PASSAGE_BLOCK


def render_passages(citations: list[Citation]) -> str:
    """Render reference citations into the numbered context block for the judge.

    Each block is keyed by ``source_id`` and page so the judge can verify
    ``[source_id p.N]`` citations exactly. Page is rendered as ``?`` when unknown.
    """
    if not citations:
        return "(no reference context was retrieved)"
    blocks: list[str] = []
    for c in citations:
        page = str(c.page) if c.page is not None else "?"
        blocks.append(
            PASSAGE_BLOCK.format(
                source_id=c.source_id,
                page=page,
                title=c.title or c.source_id,
                text=(c.snippet or "").strip(),
            )
        )
    return "\n".join(blocks)


def parse_structured(response: LlmResponse) -> dict[str, Any]:
    """Parse an LLM structured-output response into a dict, defensively.

    The GCP adapter returns the structured JSON as ``LlmResponse.text`` when a
    ``response_schema`` is set. We ``json.loads`` it; on any failure (plain text,
    truncation, a fenced block) we fall back to extracting the first balanced JSON
    object, and finally to an empty dict so callers degrade gracefully rather than
    raising on a malformed judge reply.
    """
    text = (response.text or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {"items": parsed}
    except (json.JSONDecodeError, ValueError):
        pass

    snippet = _extract_json_object(text)
    if snippet is not None:
        try:
            parsed = json.loads(snippet)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass
    return {}


def _extract_json_object(text: str) -> str | None:
    """Return the first balanced ``{...}`` block in ``text``, or None."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def build_llm_request(
    system_instruction: str,
    user_content: str,
    model: str | None,
    response_schema: dict | None,
    thinking: ThinkingLevel = ThinkingLevel.HIGH,
    temperature: float = 0.0,
    max_output_tokens: int = 2048,
) -> LlmRequest:
    """Assemble an ``LlmRequest`` with a single user message and a system prompt.

    ``model=None`` lets the adapter pick its configured default (the reasoning / judge
    model, ``gemini-3.5-flash``); thinking defaults to HIGH and temperature to 0.0 for
    a deterministic, reproducible judgement.
    """
    return LlmRequest(
        messages=(LlmMessage(role="user", content=user_content),),
        system_instruction=system_instruction,
        model=model,
        thinking=thinking,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        response_schema=response_schema,
    )


def clamp(value: Any, default: float = 0.0) -> float:
    """Clamp a numeric score into [0.0, 1.0], defaulting non-numerics to ``default``."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(f):
        return default
    return max(0.0, min(1.0, f))


def as_bool(value: Any, default: bool = False) -> bool:
    """Coerce a model-emitted value into a bool defensively."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1", "blocked", "safe"}
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def as_str_list(value: Any) -> list[str]:
    """Coerce an arbitrary model value into a list of stripped non-empty strings."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return []


def maybe_record_usage(tracer: Any, response: Any) -> None:
    """Emit token usage to the tracer for FinOps, defensively (never fatal)."""
    try:
        usage = getattr(response, "usage", None)
        model = getattr(response, "model", "") or ""
        if usage is not None and hasattr(tracer, "record_token_usage"):
            tracer.record_token_usage(usage, model)
    except Exception:  # noqa: BLE001 - metrics must never break an evaluation path
        return
