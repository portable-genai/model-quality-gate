"""ADK FunctionTools that expose the A4 domain services to the agent.

Each tool is a thin, side-effect-honest wrapper: it builds the relevant domain service
from a :class:`~model_quality_gate.config.Container` (so every port is bound to the adapter
selected by the active profile), invokes the service, and returns a JSON-safe dict via
:mod:`model_quality_gate.domain.serialization`.

Design notes
------------
* A report's overall verdict is a computed ``@property``, so the bare ``to_jsonable``
  walker drops it and the model would be handed a report with no verdict in it. The
  report-returning tools serialize through ``*_jsonable`` wrappers, which put the
  harness's verdict back on the dict each docstring below promises it.
* The domain services own orchestration (evaluate / red-team / gate / version; SPEC §5).
  These tools add **no** business logic of their own : the model decides *which* action to
  run, the service decides *how*.
* ``google.adk`` is imported lazily inside :func:`build_function_tools` so this module
  imports cleanly under the on-prem/test profile with no ADK installed (SPEC §4). The plain
  Python tool callables are importable and unit-testable without ADK at all.
* Every callable carries a precise type-hinted signature and a docstring: ADK derives the
  tool's name, description and JSON parameter schema from them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..config import Container, Settings, build_container
from ..pipelines.datasets import load_golden_dataset, standard_redteam_cases

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from google.adk.tools import FunctionTool

_DEFAULT_ACTOR = "ai-quality-agent"


def _container(settings: Settings | None) -> Container:
    """Build the DI container, honouring an optionally-injected ``Settings``."""
    return build_container(settings)


def _target(model: str, prompt_version: str, dataset_id: str, system: str = ""):
    from ..domain.models import EvalTarget

    return EvalTarget(
        model=model, prompt_version=prompt_version, dataset_id=dataset_id, system=system
    )


# --------------------------------------------------------------------------- #
# The four tool callables (plain functions: importable & testable without ADK).
# --------------------------------------------------------------------------- #
def evaluate(
    model: str,
    prompt_version: str,
    dataset_id: str,
    actor: str = _DEFAULT_ACTOR,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Evaluate a target against a golden dataset on the model-risk metrics.

    Args:
      model: the model under evaluation (e.g. "gemini-3.5-flash").
      prompt_version: the prompt version the target was built with.
      dataset_id: the golden dataset id to evaluate against.
      actor: identity the request is made for (audit trail).

    Returns:
      A JSON-safe ``EvalReport`` dict (per-metric score / threshold / passed, overall passed).
    """
    from ..api.deps import build_evaluation_service
    from ..domain.serialization import eval_report_jsonable

    service = build_evaluation_service(_container(settings))
    dataset = load_golden_dataset(dataset_id)
    report = service.evaluate(_target(model, prompt_version, dataset_id), dataset, actor)
    return eval_report_jsonable(report)


def red_team(
    model: str,
    prompt_version: str,
    actor: str = _DEFAULT_ACTOR,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Run the adversarial red-team harness against a target.

    Args:
      model: the model under test.
      prompt_version: the prompt version the target was built with.
      actor: identity the request is made for (audit trail).

    Returns:
      A JSON-safe ``RedTeamReport`` dict (per-probe blocked/passed, overall passed).
    """
    from ..api.deps import build_redteam_service
    from ..domain.serialization import redteam_report_jsonable

    service = build_redteam_service(_container(settings))
    report = service.run(_target(model, prompt_version, ""), standard_redteam_cases(), actor)
    return redteam_report_jsonable(report)


def promotion_gate(
    model: str,
    prompt_version: str,
    dataset_id: str,
    actor: str = _DEFAULT_ACTOR,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Run the full PASS/FAIL promotion gate (eval AND red-team) for a target.

    Args:
      model: the model under evaluation.
      prompt_version: the prompt version the target was built with.
      dataset_id: the golden dataset id to gate against.
      actor: identity the request is made for (audit trail).

    Returns:
      A JSON-safe ``GateDecision`` dict (passed, model_card_ref, MRM evidence, caveats).
    """
    from ..api.deps import build_gate_service
    from ..domain.serialization import gate_decision_jsonable

    service = build_gate_service(_container(settings))
    dataset = load_golden_dataset(dataset_id)
    decision = service.gate(
        _target(model, prompt_version, dataset_id), dataset, standard_redteam_cases(), actor
    )
    return gate_decision_jsonable(decision)


def version_prompt(
    name: str,
    version: str,
    template: str,
    actor: str = _DEFAULT_ACTOR,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Register a versioned, checksummed prompt (MRM change-control evidence).

    Args:
      name: the logical prompt name (e.g. "compliance-qa").
      version: the version label (e.g. "v3").
      template: the prompt template text.
      actor: identity the request is made for (audit trail).

    Returns:
      A JSON-safe ``PromptVersion`` dict (with its content checksum).
    """
    from ..api.deps import build_prompt_service
    from ..domain.models import PromptVersion
    from ..domain.serialization import to_jsonable

    service = build_prompt_service(_container(settings))
    stored = service.register(PromptVersion(name=name, version=version, template=template), actor)
    return to_jsonable(stored)


TOOL_FUNCTIONS = (evaluate, red_team, promotion_gate, version_prompt)


def build_function_tools() -> list[FunctionTool]:
    """Wrap each domain-service callable as an ADK ``FunctionTool``.

    ADK introspects each function's signature and docstring to derive the tool name,
    description and parameter JSON schema. ``google.adk`` is imported here (lazily) so the
    module is import-safe without ADK installed (SPEC §4).
    """
    from google.adk.tools import FunctionTool

    return [FunctionTool(func=fn) for fn in TOOL_FUNCTIONS]
