"""Serve the governed tool catalog model-quality-gate already declares, over MCP 2026-07-28.

The catalog declared four governed tools and served none of them: there was no MCP server
process anywhere in the fleet. This supplies the callables that answer the existing catalog and
declares nothing new. `hex_service_kit.mcpserve.bind` refuses a mismatch in either direction at
start-up.

**`promotion_gate` returns a DECISION and promotes nothing**, which is the standing rule that
nothing auto-executes. The gate service scores a target against the reviewed bars and reports a
verdict; acting on that verdict is a separate, human step, and no tool here performs it. A tool
that promoted a model on being called would put the promotion decision on whatever could open a
stdio pipe.

`version_prompt` is the one WRITE in this catalog, and it is a narrow one: it registers a prompt
version, which is an append to a versioned record rather than a change to any existing one. The
service computes the checksum itself, so a caller cannot register a template under a checksum
that does not match it.

MCP stdio verifies no end user, so the caller is recorded as a SERVICE caller.
"""

from __future__ import annotations

from typing import Any

from hex_service_kit import mcpserve

from ..api import deps
from ..domain.models import EvalTarget, PromptVersion
from ..pipelines.datasets import standard_redteam_cases

#: The tools this module answers, as data, so a test can hold it against the catalog.
HANDLER_NAMES: tuple[str, ...] = ("evaluate", "red_team", "promotion_gate", "version_prompt")


def _model_and_prompt(arguments: dict[str, Any]) -> tuple[str, str]:
    """The two identifiers every tool here names: which model, at which prompt version."""
    return (
        str(arguments.get("model", "") or ""),
        str(arguments.get("prompt_version", "") or ""),
    )


def _target(arguments: dict[str, Any]) -> EvalTarget:
    """The target for the two tools that score against a NAMED dataset."""
    model, prompt_version = _model_and_prompt(arguments)
    return EvalTarget(
        model=model,
        prompt_version=prompt_version,
        dataset_id=str(arguments.get("dataset_id", "") or ""),
    )


def _redteam_target(arguments: dict[str, Any]) -> EvalTarget:
    """The target for red-teaming, which runs standard cases rather than a dataset.

    ``red_team`` used to build its target through :func:`_target`, so it read a ``dataset_id``
    its own schema never declared and its run never used: the cases come from
    ``standard_redteam_cases()``. The value reached the audited target unset, and a caller who
    believed a dataset was in scope had no way to say so and no way to find out otherwise.
    Stating the absence here is the honest shape -- red-teaming has no dataset, rather than an
    empty one.
    """
    model, prompt_version = _model_and_prompt(arguments)
    return EvalTarget(model=model, prompt_version=prompt_version, dataset_id="")


def _dataset(dataset_id: str) -> Any:
    dataset = deps.get_dataset_store().get(dataset_id)
    if dataset is None:
        # Naming a dataset that does not exist is a caller error, and saying so is better than
        # scoring against an empty one: an eval over zero rows reports a passing average.
        raise mcpserve.ToolDispatchError(f"no eval dataset named {dataset_id!r}")
    return dataset


def build_handlers(actor: str) -> dict[str, mcpserve.Handler]:
    """Bind each declared tool to the service that already performs it."""

    def evaluate(**arguments: Any) -> Any:
        target = _target(arguments)
        return deps.get_evaluation_service().evaluate(
            target, _dataset(target.dataset_id), actor=actor
        )

    def red_team(**arguments: Any) -> Any:
        return deps.get_redteam_service().run(
            _redteam_target(arguments), standard_redteam_cases(), actor
        )

    def promotion_gate(**arguments: Any) -> Any:
        target = _target(arguments)
        return deps.get_gate_service().gate(
            target, _dataset(target.dataset_id), standard_redteam_cases(), actor
        )

    def version_prompt(**arguments: Any) -> Any:
        return deps.get_prompt_service().register(
            PromptVersion(
                name=str(arguments.get("name", "") or ""),
                version=str(arguments.get("version", "") or ""),
                template=str(arguments.get("template", "") or ""),
            ),
            actor=actor,
        )

    return {
        "evaluate": evaluate,
        "red_team": red_team,
        "promotion_gate": promotion_gate,
        "version_prompt": version_prompt,
    }


def build_server(actor: str, *, with_audit_tools: bool = True) -> Any:
    """Build the MCP server for model-quality-gate's catalog, refusing on any catalog/handler
    mismatch.
    """
    container = deps.get_container()
    return mcpserve.build_server(
        name="model-quality-gate",
        version=str(getattr(container.settings, "version", "") or "0.0.1"),
        catalog=container.tool_catalog,
        handlers=build_handlers(actor),
        audit_store=getattr(container, "audit", None) if with_audit_tools else None,
    )
