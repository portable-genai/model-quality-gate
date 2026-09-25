"""Sampling is decided per call: pinned where output is compared, free where it is prose.

**History.** This file began as ``test_grounded_requests_do_not_sample.py``. On 2026-08-26, in
``cdd-sow-research``, two runs of one identical case minutes apart returned different scores,
because the shared request builder defaulted to ``temperature=0.2`` and every grounded call
sampled. The response then was to pin the request TYPE's default to 0.0, so a call site that
omitted the parameter could not sample.

**What changed (owner decision, 2026-09-23).** A blanket pin is the wrong default in both
directions. It pins prose nobody compares, and a model that rejects the parameter outright
(Opus 5, Fable 5) cannot be called at all while every request carries one. So the type and the
builder now default to ``None``, which SENDS NO TEMPERATURE, and the decision moved to the call
site. In this gate nearly every model call feeds a PASS/FAIL, so nearly every one stays pinned:

* **pinned (0.0)**: the target's reply to a red-team probe (compared against the probe's
  expected outcome), the red-team judge (emits the blocked/passed labels the verdict is computed
  from), and both ``classify`` methods (a label matched against a fixed set).
* **free (None, omitted on the wire)**: the ADK agent, which narrates what its tools return;
  every score and PASS/FAIL comes from those tools, never from its prose.

**Temperature 0 is not a promise of determinism, and nothing here asserts one.** A hosted model
can still vary across batching and model revisions.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
from pathlib import Path

import pytest
from tests.fixtures import sample_targets
from tests.fixtures.fake_genai import FakeGenaiClient, install_fake_genai

from model_quality_gate.adapters.gcp.gemini_llm import GeminiLLMAdapter
from model_quality_gate.adapters.gcp.gemini_redteam import GeminiRedTeamAdapter
from model_quality_gate.config import Settings
from model_quality_gate.domain import _grounded
from model_quality_gate.domain.models import LlmMessage, LlmRequest
from model_quality_gate.pipelines.datasets import standard_redteam_cases

_REQUEST = LlmRequest(messages=(LlmMessage(role="user", content="Explain the verdict."),))


def _gcp_settings() -> Settings:
    return dataclasses.replace(Settings.load("config/settings.yaml"), profile="gcp")


def test_the_request_type_and_the_builder_leave_sampling_to_the_call_site() -> None:
    assert LlmRequest.__dataclass_fields__["temperature"].default is None
    signature = inspect.signature(_grounded.build_llm_request)
    assert signature.parameters["temperature"].default is None


def test_a_free_request_sends_no_temperature_and_a_pinned_one_sends_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Free means ABSENT from the generation config, never 1.0."""
    install_fake_genai(monkeypatch)
    adapter = GeminiLLMAdapter(_gcp_settings())
    fake = FakeGenaiClient()
    adapter._client = fake
    adapter.generate(_REQUEST)
    adapter.generate(LlmRequest(messages=_REQUEST.messages, temperature=0.0))
    assert "temperature" not in fake.calls[0][1]
    assert fake.calls[1][1]["temperature"] == 0.0


def test_classification_stays_pinned(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_genai(monkeypatch)
    adapter = GeminiLLMAdapter(_gcp_settings())
    fake = FakeGenaiClient(reply="fail")
    adapter._client = fake
    assert adapter.classify("text", ["pass", "fail"]) == "fail"
    assert fake.calls[0][1]["temperature"] == 0.0


def test_both_red_team_calls_stay_pinned(monkeypatch: pytest.MonkeyPatch) -> None:
    """The probe reply and the judge's labels both feed the gate's PASS/FAIL."""
    install_fake_genai(monkeypatch)
    adapter = GeminiRedTeamAdapter(_gcp_settings())
    fake = FakeGenaiClient()
    adapter._client = fake
    adapter.run(sample_targets.SAMPLE_TARGET, standard_redteam_cases()[:1])
    assert [config["temperature"] for _, config in fake.calls] == [0.0, 0.0]


def test_the_narrating_agent_sends_no_temperature() -> None:
    """Read from source: building the agent needs the ADK, which this offline gate lacks."""
    source = Path("src/model_quality_gate/agent/root_agent.py").read_text(encoding="utf-8")
    configs = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "GenerateContentConfig"
    ]
    assert configs, "the agent no longer builds a generation config; re-point this test"
    for config in configs:
        assert "temperature" not in {k.arg for k in config.keywords}, (
            "the agent narrates tool results and is left free: omit temperature, never 1.0"
        )
