"""The laptop ``live`` profile: the judge LLM on the local model, everything else as ``local``.

Offline: the kit client runs against a fake transport, so no model server is needed. What is
pinned here is the adapter's mapping (messages in, validated JSON and the answering model id
out), the kit's retry on a fenced-then-invalid answer, and the profile's wiring and posture.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

import pytest
from hex_service_kit.localmodel import (
    LocalModelClient,
    LocalModelOutputError,
    LocalModelSettings,
    LocalModelUnavailable,
)

from model_quality_gate.adapters.live.llm import LocalModelLLMAdapter
from model_quality_gate.config import (
    Container,
    LocalSettings,
    Settings,
    resolve_profile,
)
from model_quality_gate.domain.models import LlmMessage, LlmRequest, TokenUsage

CONFIG_PATH = "config/settings.yaml"

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"score": {"type": "number"}, "supported": {"type": "boolean"}},
    "required": ["score", "supported"],
}


class FakeServer:
    """Answers each chat call with the next scripted reply and records what it was sent."""

    def __init__(self, *replies: str, model: str = "served-model", usage: Any = None) -> None:
        self.replies = list(replies)
        self.model = model
        self.usage = usage
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, body: bytes | None, timeout: float) -> bytes:
        payload = json.loads(body or b"{}")
        self.calls.append(payload)
        reply: dict[str, Any] = {
            "model": self.model,
            "choices": [{"message": {"role": "assistant", "content": self.replies.pop(0)}}],
        }
        if self.usage is not None:
            reply["usage"] = self.usage
        return json.dumps(reply).encode()


def _adapter(server: Any) -> LocalModelLLMAdapter:
    client = LocalModelClient(LocalModelSettings(), transport=server)
    return LocalModelLLMAdapter(Settings(), client=client)


def _request(**overrides: Any) -> LlmRequest:
    base: dict[str, Any] = {
        "messages": (LlmMessage(role="user", content="Is the claim supported?"),),
        "system_instruction": "You are a strict groundedness judge.",
        "model": "gemini-3.5-flash",
        "temperature": 0.0,
        "max_output_tokens": 512,
        "response_schema": _SCHEMA,
    }
    base.update(overrides)
    return LlmRequest(**base)


def test_a_structured_call_returns_validated_json_from_the_model_that_answered() -> None:
    server = FakeServer('{"score": 0.9, "supported": true}', usage={"prompt_tokens": 7})
    response = _adapter(server).generate(_request())

    assert json.loads(response.text) == {"score": 0.9, "supported": True}
    assert response.raw == {"score": 0.9, "supported": True}
    # The id that answered, never the Gemini id the request named.
    assert response.model == "served-model"
    assert response.usage == TokenUsage(input_tokens=7, output_tokens=0)
    sent = server.calls[0]
    assert sent["messages"][0]["role"] == "system"
    assert sent["messages"][0]["content"].startswith("You are a strict groundedness judge.")
    assert '"required": ["score", "supported"]' in sent["messages"][0]["content"]
    assert sent["messages"][1] == {"role": "user", "content": "Is the claim supported?"}
    assert sent["temperature"] == 0.0
    assert sent["max_tokens"] == 512


def test_a_fenced_answer_missing_a_field_is_sent_back_and_the_retry_is_used() -> None:
    server = FakeServer(
        '```json\n{"score": 0.4}\n```',
        '```json\n{"score": 0.4, "supported": false}\n```',
    )
    response = _adapter(server).generate(_request())

    assert json.loads(response.text) == {"score": 0.4, "supported": False}
    assert len(server.calls) == 2
    correction = server.calls[1]["messages"][-1]["content"]
    assert "supported" in correction


def test_a_model_that_never_answers_in_schema_raises_rather_than_scoring() -> None:
    server = FakeServer("not json", "still not json", "no")
    with pytest.raises(LocalModelOutputError):
        _adapter(server).generate(_request())
    assert len(server.calls) == 3


def test_an_unstructured_call_returns_text_and_no_usage_reads_as_zero() -> None:
    server = FakeServer("A short narrative.")
    response = _adapter(server).generate(_request(response_schema=None))

    assert response.text == "A short narrative."
    assert response.model == "served-model"
    # LlmResponse.usage is not optional in this repo, so unreported usage is the zero default.
    assert response.usage == TokenUsage()
    assert "Answer with a single JSON value" not in json.dumps(server.calls[0])


def test_the_request_temperature_is_passed_through_unchanged() -> None:
    server = FakeServer("ok")
    _adapter(server).generate(_request(response_schema=None, temperature=0.7))
    assert server.calls[0]["temperature"] == 0.7


def test_a_free_request_sends_no_temperature_at_all() -> None:
    """``None`` is passed through as None, and the kit client then omits the field."""
    server = FakeServer("ok")
    _adapter(server).generate(_request(response_schema=None, temperature=None))
    assert "temperature" not in server.calls[0]


def test_a_server_that_does_not_answer_says_how_to_start_one() -> None:
    def refused(url: str, body: bytes | None, timeout: float) -> bytes:
        raise ConnectionRefusedError("connection refused")

    with pytest.raises(LocalModelUnavailable, match="mlx_vlm.server"):
        _adapter(refused).generate(_request())


def test_classify_picks_the_label_the_model_named() -> None:
    server = FakeServer("The answer is: block.")
    assert _adapter(server).classify("text", ["pass", "block"]) == "block"
    assert server.calls[0]["temperature"] == 0.0


def _live_settings() -> Settings:
    base = Settings.load(CONFIG_PATH)
    return dataclasses.replace(
        base,
        profile="live",
        local=LocalSettings(
            db_path=":memory:",
            audit_path=":memory:",
            registry_path=":memory:",
            model_cards_path=":memory:",
            metrics_path=":memory:",
            datasets_path=":memory:",
        ),
    )


def test_the_container_builds_every_port_under_live_with_no_server() -> None:
    settings = _live_settings()
    container = Container(settings)
    for port_name, binding in settings.adapters.items():
        adapter = container._bind(port_name)  # noqa: SLF001 - profile wiring contract
        module, _, class_name = binding["live"].partition(":")
        assert (type(adapter).__module__, type(adapter).__name__) == (module, class_name)
    assert isinstance(container.llm, LocalModelLLMAdapter)


def test_live_rebinds_only_the_llm_port() -> None:
    adapters = Settings.load(CONFIG_PATH).adapters
    differs = sorted(name for name, b in adapters.items() if b["live"] != b["local"])
    assert differs == ["llm"]


def test_live_takes_the_laptop_posture_local_takes() -> None:
    live = resolve_profile(environ={"AI_QUALITY_PROFILE": "live"})
    local = resolve_profile(environ={"AI_QUALITY_PROFILE": "local"})
    assert live.profile == "live"
    assert (live.exposure_profile, live.bind_profile) == (
        local.exposure_profile,
        local.bind_profile,
    )
    assert live.bind_profile == "local"


def test_live_is_demo_only_like_local_and_never_promotion_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from model_quality_gate.api import deps
    from model_quality_gate.api.app import _capability_manifest

    settings = dataclasses.replace(Settings.load(CONFIG_PATH), profile="live")
    monkeypatch.setattr(deps, "get_settings", lambda: settings)
    manifest = _capability_manifest()
    assert manifest.demo_only is True
    assert manifest.production_ready is False
    assert {item.assurance for item in manifest.capabilities} == {"demo-only"}
