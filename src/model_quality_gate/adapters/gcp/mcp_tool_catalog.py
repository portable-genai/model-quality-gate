"""MCP tool-catalog adapter (ToolCatalogPort).

Backs the domain ``ToolCatalogPort`` with the governed, least-privilege set of tools A4
exposes over MCP (Model Context Protocol). The catalog is declared statically here so the
governed surface is auditable; an MCP server (``mcp`` SDK) publishes it at runtime. The
``mcp`` import is lazy so the on-prem and test profiles import without it.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import ToolSpec

# The governed A4 tool surface, mirroring the four agent skills.
_TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="evaluate",
        description="Evaluate a target (model + prompt version) against a golden dataset.",
        input_schema={
            "type": "object",
            "properties": {
                "model": {"type": "string"},
                "prompt_version": {"type": "string"},
                "dataset_id": {"type": "string"},
            },
            "required": ["model", "prompt_version", "dataset_id"],
        },
    ),
    ToolSpec(
        name="red_team",
        description="Run the adversarial red-team harness against a target.",
        input_schema={
            "type": "object",
            "properties": {"model": {"type": "string"}, "prompt_version": {"type": "string"}},
            "required": ["model", "prompt_version"],
        },
    ),
    ToolSpec(
        name="promotion_gate",
        description="Run the full PASS/FAIL promotion gate for a target.",
        input_schema={
            "type": "object",
            "properties": {
                "model": {"type": "string"},
                "prompt_version": {"type": "string"},
                "dataset_id": {"type": "string"},
            },
            "required": ["model", "prompt_version", "dataset_id"],
        },
    ),
    ToolSpec(
        name="version_prompt",
        description="Register a versioned, checksummed prompt (MRM change-control).",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "version": {"type": "string"},
                "template": {"type": "string"},
            },
            "required": ["name", "version", "template"],
        },
    ),
)


class McpToolCatalogAdapter:
    """Governed MCP tool catalog for A4."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._tools = {tool.name: tool for tool in _TOOLS}

    def list_tools(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def get_tool(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)
