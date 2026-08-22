"""Local tool-catalog adapter (ToolCatalogPort) : in-process MCP tool catalog.

The ``local`` profile's stand-in for the governed **MCP** tool catalog: a small,
deterministic in-process set of least-privilege tool specs for the A4 gate skills.
SDK-free and unconditional (there is no emulator for the tool catalog).
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import ToolSpec


class LocalToolCatalogAdapter:
    """In-process catalog of the governed tools exposed to the A4 agent."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._tools: dict[str, ToolSpec] = {
            "evaluate": ToolSpec(
                name="evaluate",
                description="Evaluate a target against a golden dataset.",
                input_schema={"type": "object", "properties": {"target": {"type": "string"}}},
            ),
            "promotion_gate": ToolSpec(
                name="promotion_gate",
                description="Run the full PASS/FAIL promotion gate for a target.",
                input_schema={"type": "object", "properties": {"target": {"type": "string"}}},
            ),
        }

    def list_tools(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def get_tool(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)
