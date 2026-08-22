"""A2A AgentCard for the A4 AI Quality & Model-Risk Platform (A3 Registry).

This builds the service's discovery card : the same minimal A2A shape the
``agent-registry`` service stores and serves (SPEC §6). It is published at
``/.well-known/agent-card.json``; :func:`agent_card_document` returns the JSON-safe body
the API layer serves there.

The card advertises the four A4 skills (evaluate, red_team, promotion_gate,
version_prompt), mirroring the four ADK FunctionTools so a peer agent or the registry sees
one consistent capability surface.

This module is pure (domain models only) and imports without ADK or any Google Cloud SDK
installed (SPEC §4).
"""

from __future__ import annotations

from typing import Any

from ..config import Settings
from ..domain.models import AgentCard, AgentSkill

SKILLS: tuple[AgentSkill, ...] = (
    AgentSkill(
        id="evaluate",
        name="Model evaluation",
        description=(
            "Evaluate a target (model + prompt version) against a golden dataset on the "
            "model-risk metrics (groundedness, citation accuracy, faithfulness, safety) "
            "and return a per-metric EvalReport with thresholds."
        ),
    ),
    AgentSkill(
        id="red_team",
        name="Adversarial red-team",
        description=(
            "Run an adversarial red-team harness (prompt injection, jailbreak, "
            "PII exfiltration, harmful content, hallucination) and return a RedTeamReport "
            "with a pass/fail per probe."
        ),
    ),
    AgentSkill(
        id="promotion_gate",
        name="Promotion gate",
        description=(
            "Run the full PASS/FAIL promotion gate (eval AND red-team), write a model "
            "card plus MRM evidence, and flag borderline passes for human review."
        ),
    ),
    AgentSkill(
        id="version_prompt",
        name="Prompt versioning",
        description=(
            "Register a versioned, checksummed prompt as MRM change-control evidence so a "
            "target's exact prompt is traceable."
        ),
    ),
)

_DESCRIPTION = (
    "AI Quality & Model-Risk Platform: the production-promotion eval / red-team gate and "
    "model-risk (MRM) evidence system for APAC banking. Every B/C agent must pass A4 "
    "before promotion (rule R5). Built ports-and-adapters on the Gemini Enterprise Agent "
    "Platform (Gen AI evaluation service, BigQuery / GCS stores)."
)


def build_agent_card(settings: Settings) -> AgentCard:
    """Construct the A2A :class:`AgentCard` for this service."""
    base_url = _resolve_url(settings)
    return AgentCard(
        name="model-quality-gate",
        description=_DESCRIPTION,
        url=base_url,
        version="0.1.0",
        skills=SKILLS,
        provider="model-quality-gate",
    )


def agent_card_document(settings: Settings) -> dict[str, Any]:
    """Return the JSON-safe body to serve at ``/.well-known/agent-card.json``."""
    from ..domain.serialization import to_jsonable

    return to_jsonable(build_agent_card(settings))


def _resolve_url(settings: Settings) -> str:
    """Best-effort public URL for the card in the configured GCP region."""
    resource = settings.agent_engine.resource_name
    if resource:
        return f"https://aiplatform.googleapis.com/v1/{resource}"
    return "https://model-quality-gate.hrz.internal/a2a"
