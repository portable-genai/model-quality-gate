"""A2A registry adapter (AgentRegistryPort).

Backs the domain ``AgentRegistryPort`` by serving / resolving this service's A2A
AgentCard. In a standalone deployment the card is served locally at
``/.well-known/agent-card.json``; an in-memory store keeps any cards registered at
runtime so the A3 governance surface is consistent. When deployed inside the full
platform the ``platform`` profile swaps this for the remote A3 client.

This adapter imports no Google Cloud SDK at module level (the AgentCard is a pure domain
object), so it is import-safe under any profile.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import AgentCard


class A2ARegistryAdapter:
    """Local A2A AgentCard registry (standalone profile)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._cards: dict[str, AgentCard] = {}

    def register(self, card: AgentCard) -> None:
        self._cards[card.name] = card

    def get(self, name: str) -> AgentCard | None:
        return self._cards.get(name)

    def list(self) -> list[AgentCard]:
        return list(self._cards.values())
