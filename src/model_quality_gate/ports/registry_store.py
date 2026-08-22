"""Storage ports : prompt registry, model-card store, and metrics/drift store.

Primary GCP adapters: a **BigQuery / GCS** prompt store (versioned, checksummed
prompts), a **GCS / Model Registry** model-card store, and a **BigQuery** metrics store
that records eval reports and computes drift for the model-risk dashboards. On-prem
migration swaps these for placeholder adapters with no change to callers.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import (
    DriftSignal,
    EvalReport,
    ModelCard,
    MrmEvidence,
    PromptVersion,
)


@runtime_checkable
class PromptRegistryPort(Protocol):
    def put(self, version: PromptVersion) -> None: ...

    def get(self, name: str, version: str) -> PromptVersion | None: ...

    def list(self, name: str) -> list[PromptVersion]: ...


@runtime_checkable
class ModelCardStorePort(Protocol):
    def put(self, card: ModelCard) -> None: ...

    def get(self, model: str, version: str) -> ModelCard | None: ...

    def put_evidence(self, evidence: MrmEvidence) -> None: ...

    def get_evidence(self, run_id: str) -> MrmEvidence | None: ...


@runtime_checkable
class MetricsStorePort(Protocol):
    def record(self, report: EvalReport) -> None:
        """Persist an eval report for trend / drift analysis (BigQuery)."""
        ...

    def drift(self, model: str) -> list[DriftSignal]:
        """Return per-metric drift signals for ``model`` against its baseline."""
        ...
