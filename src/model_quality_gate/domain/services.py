"""Aggregator re-exporting the A4 orchestration services.

The services live one-per-module (``evaluation_service``, ``redteam_service``,
``gate_service``, ``prompt_service``, ``model_card_service``) so each stays focused.
This module is the single import surface the wiring layers (``api.deps``,
``agent.tools``, ``cli``) use, so they never need to know which module a service lives in.
"""

from __future__ import annotations

from .evaluation_service import EvaluationService
from .gate_service import PromotionGateService
from .model_card_service import ModelCardService
from .prompt_service import PromptVersioningService
from .redteam_service import RedTeamService

__all__ = [
    "EvaluationService",
    "RedTeamService",
    "PromotionGateService",
    "PromptVersioningService",
    "ModelCardService",
]
