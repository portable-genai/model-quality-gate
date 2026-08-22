"""PromptVersioningService : versioned, checksummed prompt change-control (SPEC §5).

Prompts are part of the model-risk surface (they shape behaviour the gate evaluates),
so every prompt version is stored with a content checksum: an MRM change-control record
that lets a model-risk officer prove which exact prompt a target was gated under. This
service registers and resolves prompt versions through the ``PromptRegistryPort`` (a
BigQuery / GCS store in the gcp profile, a placeholder on-prem).

Pure domain code : no Google Cloud / ADK imports.
"""

from __future__ import annotations

import hashlib
from contextlib import nullcontext
from typing import Any

from .errors import AssurancePersistenceError
from .models import AuditEvent, Decision, PromptVersion


def checksum_template(template: str) -> str:
    """Return a stable content checksum for a prompt template (sha256, first 16 hex)."""
    digest = hashlib.sha256(template.encode("utf-8")).hexdigest()
    return digest[:16]


class PromptVersioningService:
    """Register and resolve versioned prompts. Signature fixed by SPEC §5."""

    def __init__(
        self,
        prompt_registry: Any,
        tracer: Any,
        audit: Any,
    ) -> None:
        self._registry = prompt_registry
        self._tracer = tracer
        self._audit = audit

    def register(self, version: PromptVersion, actor: str) -> PromptVersion:
        """Register ``version``, computing its checksum if absent, and audit it."""
        span = self._tracer.span(
            "prompt.register", action="version_prompt", actor=actor, prompt=version.name
        )
        with span if span is not None else nullcontext():
            stored = self._with_checksum(version)
            self._registry.put(stored)
            self._write_audit(
                actor,
                f"registered prompt {stored.name}@{stored.version} ({stored.checksum})",
                {"name": stored.name, "version": stored.version, "checksum": stored.checksum},
            )
            return stored

    def get(self, name: str, version: str) -> PromptVersion | None:
        """Resolve a single prompt version by name + version."""
        return self._registry.get(name, version)

    def list(self, name: str) -> list[PromptVersion]:
        """List every stored version of a named prompt."""
        return list(self._registry.list(name) or [])

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _with_checksum(version: PromptVersion) -> PromptVersion:
        if version.checksum:
            return version
        return PromptVersion(
            name=version.name,
            version=version.version,
            template=version.template,
            created_at=version.created_at,
            checksum=checksum_template(version.template),
        )

    def _write_audit(self, actor: str, summary: str, metadata: dict[str, str]) -> None:
        event = AuditEvent(
            action="version_prompt",
            actor=actor,
            decision=Decision.ALLOWED,
            redacted_prompt=summary,
            metadata=metadata,
        )
        try:
            self._audit.record(event)
        except Exception as exc:  # noqa: BLE001 - convert adapter failure to domain contract
            raise AssurancePersistenceError(
                f"prompt version stored but immutable audit persistence failed: {exc}"
            ) from exc
