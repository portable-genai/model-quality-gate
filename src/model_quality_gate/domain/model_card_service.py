"""ModelCardService : model-card storage and retrieval (SPEC §5, P-07).

A model card captures a model's intended use, the metrics it was last evaluated on, and
its known limitations : the MRM (model-risk management) evidence a regulator or model-risk
committee inspects. This service registers and resolves model cards through the
``ModelCardStorePort`` (GCS / a model registry in the gcp profile, a placeholder on-prem)
and audits every write.

Pure domain code : no Google Cloud / ADK imports.
"""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any

from .errors import AssurancePersistenceError
from .models import AuditEvent, Decision, ModelCard


class ModelCardService:
    """Store and resolve model cards. Signature fixed by SPEC §5."""

    def __init__(
        self,
        model_card_store: Any,
        tracer: Any,
        audit: Any,
    ) -> None:
        self._store = model_card_store
        self._tracer = tracer
        self._audit = audit

    def put(self, card: ModelCard, actor: str) -> ModelCard:
        """Persist ``card`` and audit the write (MRM evidence, P-07)."""
        span = self._tracer.span(
            "model_card.put", action="model_card", actor=actor, model=card.model
        )
        with span if span is not None else nullcontext():
            self._store.put(card)
            self._write_audit(
                actor,
                f"stored model card {card.ref}",
                {"model": card.model, "version": card.version, "ref": card.ref},
            )
            return card

    def get(self, model: str, version: str) -> ModelCard | None:
        """Resolve a single model card by model + version."""
        return self._store.get(model, version)

    # ------------------------------------------------------------------ #
    # Audit
    # ------------------------------------------------------------------ #
    def _write_audit(self, actor: str, summary: str, metadata: dict[str, str]) -> None:
        event = AuditEvent(
            action="model_card",
            actor=actor,
            decision=Decision.ALLOWED,
            redacted_prompt=summary,
            metadata=metadata,
        )
        try:
            self._audit.record(event)
        except Exception as exc:  # noqa: BLE001 - convert adapter failure to domain contract
            raise AssurancePersistenceError(
                f"model card stored but immutable audit persistence failed: {exc}"
            ) from exc
