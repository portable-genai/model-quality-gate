"""Ports : the abstract interfaces (the hexagon boundary).

Every port is a ``typing.Protocol`` so adapters need only structural conformance and
contract tests can verify any adapter (GCP, remote-platform, or on-prem placeholder)
satisfies the same contract.
"""

from .dataset_store import DatasetStorePort
from .evaluation import EvaluationPort, RedTeamPort
from .generation import LLMPort
from .governance import AgentRegistryPort, ToolCatalogPort
from .identity import EndUserAuthUnavailableError, IdentityPort
from .knowledge import KnowledgeBaseClientPort
from .observability import AuditSinkPort, ObservabilityTracerPort, TokenUsage
from .registry_store import (
    MetricsStorePort,
    ModelCardStorePort,
    PromptRegistryPort,
)

__all__ = [
    "EvaluationPort",
    "RedTeamPort",
    "DatasetStorePort",
    "PromptRegistryPort",
    "ModelCardStorePort",
    "MetricsStorePort",
    "KnowledgeBaseClientPort",
    "LLMPort",
    "AuditSinkPort",
    "ObservabilityTracerPort",
    "TokenUsage",
    "AgentRegistryPort",
    "ToolCatalogPort",
    "IdentityPort",
    "EndUserAuthUnavailableError",
]
