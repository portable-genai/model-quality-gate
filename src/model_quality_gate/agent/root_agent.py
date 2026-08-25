"""Root ADK agent for the A4 AI Quality & Model-Risk Platform, on Agent Runtime.

This is the agent the Gemini Enterprise Agent Platform **Agent Runtime** (ex-Agent
Engine) hosts. It wires together the four domain-service :class:`FunctionTool` wrappers
(``agent.tools``) and the reasoning model ``settings.models.reasoning``
(``gemini-3.5-flash``) at ``thinking=high`` (SPEC §3).

ADK convention is honoured two ways: the module exposes a ``root_agent`` attribute (what
ADK / ``adk web`` / Agent Runtime discover by default) **and** a
``build_root_agent(settings)`` factory for explicit, test-friendly construction.

Import safety (SPEC §4)
-----------------------
``google.adk`` is heavy and GCP-only. All ADK imports are quarantined inside
:func:`build_root_agent`, and the module-level ``root_agent`` is built lazily via
:class:`_LazyRootAgent` so merely importing this module never requires ADK : the
on-prem/test profile imports it cleanly.

Deploying to Agent Runtime
--------------------------
Wrap and deploy with the Agent Platform SDK (configured GCP region)::

    from vertexai import agent_engines
    from model_quality_gate.agent.root_agent import build_root_agent
    from model_quality_gate.config import Settings

    remote = agent_engines.create(
        build_root_agent(Settings.load()),
        requirements=["google-adk==2.7.1", "model-quality-gate"],
    )  # -> reasoningEngine resource; record it in settings.agent_engine.resource_name

Exposing over A2A: ``to_a2a(build_root_agent(settings))`` produces an A2A app that serves
``/.well-known/agent-card.json`` (see :func:`to_a2a_app` and ``agent.agent_card``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..config import Settings

if TYPE_CHECKING:  # pragma: no cover - typing only
    from google.adk.agents import LlmAgent

ROOT_AGENT_NAME = "model_quality_gate_model_risk"

_ROOT_INSTRUCTION = (
    "You are the A4 AI Quality & Model-Risk gate for APAC banking. You evaluate AI "
    "targets (a model plus a prompt version) against golden datasets, run adversarial "
    "red-team probes, and decide whether a target may be promoted.\n\n"
    "Routing:\n"
    "- 'Evaluate <model> on <dataset>' -> call evaluate.\n"
    "- 'Red-team <model>' -> call red_team.\n"
    "- 'Can <model>@<version> be promoted on <dataset>?' -> call promotion_gate.\n"
    "- 'Register prompt <name> <version>' -> call version_prompt.\n\n"
    "Rules:\n"
    "- A target may be promoted ONLY if it passes every eval threshold AND the red-team "
    "harness blocks every probe. Never report a PASS unless both hold.\n"
    "- State plainly when a gate verdict requires human review (a borderline pass) so a "
    "model-risk officer signs off (maker-checker).\n"
    "- Always reference the model card and MRM evidence the gate produced.\n"
    "- You evaluate models against datasets; you do not process customer personal data."
)


def build_root_agent(settings: Settings | None = None) -> LlmAgent:
    """Construct the root ADK ``LlmAgent`` for the A4 gate.

    Wires the four FunctionTools and runs the reasoning model at ``thinking=high``
    (SPEC §3). All ADK imports are local to this function (SPEC §4).
    """
    settings = settings or Settings.load()

    from google.adk.agents import LlmAgent
    from google.genai import types

    from .tools import build_function_tools

    tools: list[Any] = list(build_function_tools())

    # thinking=high for the reasoning model (gemini-3.5-flash) per SPEC §3.
    generate_content_config = types.GenerateContentConfig(
        temperature=0.0,
        thinking_config=types.ThinkingConfig(thinking_budget=-1),
    )

    return LlmAgent(
        name=ROOT_AGENT_NAME,
        model=settings.models.reasoning,
        description=(
            "AI quality and model-risk gate: evaluates targets, runs adversarial "
            "red-team probes, and renders PASS/FAIL promotion decisions with MRM evidence."
        ),
        instruction=_ROOT_INSTRUCTION,
        tools=tools,
        generate_content_config=generate_content_config,
    )


def to_a2a_app(settings: Settings | None = None) -> Any:
    """Expose the root agent as an A2A app (serves ``/.well-known/agent-card.json``).

    Thin wrapper over ADK's ``to_a2a`` so peers can discover and call the gate over A2A
    v1.0 (SPEC §3/§6). ADK is imported lazily (SPEC §4).
    """
    from google.adk.a2a.utils.agent_to_a2a import to_a2a

    return to_a2a(build_root_agent(settings))


class _LazyRootAgent:
    """Lazy proxy so ``import root_agent`` never pulls in ADK.

    ADK discovers a module-level ``root_agent``. We must expose that name without forcing
    ADK to be importable at module import time (on-prem/test profile, SPEC §4). The real
    ``LlmAgent`` is built on first attribute access and cached.
    """

    __slots__ = ("_agent",)

    def __init__(self) -> None:
        self._agent: LlmAgent | None = None

    def _resolve(self) -> LlmAgent:
        if self._agent is None:
            self._agent = build_root_agent()
        return self._agent

    def __getattr__(self, name: str) -> Any:
        return getattr(self._resolve(), name)

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        state = "unbuilt" if self._agent is None else "built"
        return f"<LazyRootAgent {ROOT_AGENT_NAME} ({state})>"


# ADK convention: a module-level ``root_agent`` the runtime discovers. Lazy so importing
# this module is safe without ADK installed (SPEC §4).
root_agent = _LazyRootAgent()
