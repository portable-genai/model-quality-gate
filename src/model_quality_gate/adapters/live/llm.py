"""Live LLM adapter (LLMPort): the judge model is the laptop's local open-weight model.

Delegates every call to :class:`hex_service_kit.localmodel.LocalModelClient`, the one client the
fleet's laptop ``live`` profiles share. The server, the model id and the timeout are read by
:meth:`~hex_service_kit.localmodel.LocalModelSettings.from_env` (``LOCAL_MODEL_URL``,
``LOCAL_MODEL``, ``LOCAL_MODEL_TIMEOUT``, three-state), never by this module.

A request that carries ``response_schema`` is a structured call: the kit puts the schema in the
prompt, strips a fence, validates the answer and asks again with the problem stated, so what
comes back is validated JSON or a :class:`~hex_service_kit.localmodel.LocalModelOutputError`.
The kit's two errors propagate unchanged, as the Gemini adapter's SDK errors do: the local
server did not answer (:class:`~hex_service_kit.localmodel.LocalModelUnavailable`, whose message
ends with the start recipe) or answered with nothing usable.

``request.model`` names a Gemini id on the managed stack and is not honoured here: the laptop
serves one model, and the response names the id that actually answered.
"""

from __future__ import annotations

import json

from hex_service_kit.localmodel import (
    LocalCompletion,
    LocalModelClient,
    LocalModelSettings,
)

from ...config import Settings
from ...domain.models import LlmRequest, LlmResponse, TokenUsage

#: The port's roles mapped onto the chat-completions roles the local server speaks.
_ROLES = {"user": "user", "model": "assistant", "assistant": "assistant", "system": "system"}


class LocalModelLLMAdapter:
    """The judge LLM on the laptop's local model server, via the shared kit client."""

    def __init__(self, settings: Settings, *, client: LocalModelClient | None = None) -> None:
        self._settings = settings
        self._client = client or LocalModelClient(LocalModelSettings.from_env())

    # ------------------------------------------------------------------ #
    # LLMPort
    # ------------------------------------------------------------------ #
    def generate(self, request: LlmRequest) -> LlmResponse:
        messages: list[dict[str, str]] = []
        if request.system_instruction:
            messages.append({"role": "system", "content": request.system_instruction})
        messages.extend(
            {"role": _ROLES.get(m.role, "user"), "content": m.content} for m in request.messages
        )
        if request.response_schema:
            completion = self._client.complete_json(
                messages,
                schema=request.response_schema,
                temperature=request.temperature,
                max_tokens=request.max_output_tokens,
            )
            data = completion.data
            return LlmResponse(
                text=json.dumps(data),
                usage=_usage(completion),
                model=completion.model,
                raw=data if isinstance(data, dict) else None,
            )
        completion = self._client.complete(
            messages, temperature=request.temperature, max_tokens=request.max_output_tokens
        )
        return LlmResponse(text=completion.text, usage=_usage(completion), model=completion.model)

    def classify(self, text: str, labels: list[str]) -> str:
        prompt = f"Classify the text into exactly one label from {labels}.\n\nTEXT:\n{text}"
        completion = self._client.complete(
            [{"role": "user", "content": prompt}], temperature=0.0, max_tokens=64
        )
        answer = completion.text.strip().lower()
        for label in labels:
            if label.lower() in answer:
                return label
        return labels[0] if labels else ""


def _usage(completion: LocalCompletion) -> TokenUsage:
    """The kit's usage, or zero counts when the server reported none.

    ``LlmResponse.usage`` is not optional in this repo's response type, so an unreported usage
    becomes the type's zero default rather than ``None``. A local server that reports no usage
    (MLX) therefore reads as zero tokens here, and nothing downstream prices a local call.
    """
    return completion.usage if completion.usage is not None else TokenUsage()
