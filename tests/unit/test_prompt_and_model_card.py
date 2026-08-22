"""Unit tests for PromptVersioningService and ModelCardService (SPEC §5).

* PromptVersioningService registers checksummed prompt versions (MRM change-control).
* ModelCardService stores / resolves model cards (MRM evidence, P-07).
"""

from __future__ import annotations

import pytest
from tests.fixtures import sample_targets

from model_quality_gate.domain.models import Decision, ModelCard, PromptVersion

ACTOR = "model-risk@bank.test"


# --------------------------------------------------------------------------- #
# PromptVersioningService
# --------------------------------------------------------------------------- #
def test_register_computes_checksum_when_absent(prompt_service, prompt_registry):
    stored = prompt_service.register(sample_targets.SAMPLE_PROMPT, actor=ACTOR)

    assert isinstance(stored, PromptVersion)
    assert stored.checksum, "a registered prompt must carry a content checksum"
    # The same template registered twice yields the same checksum (deterministic).
    again = prompt_service.register(sample_targets.SAMPLE_PROMPT, actor=ACTOR)
    assert again.checksum == stored.checksum
    # It is resolvable by name + version.
    resolved = prompt_service.get("compliance-qa", "v3")
    assert resolved is not None
    assert resolved.checksum == stored.checksum


def test_register_audits_the_change(prompt_service, audit):
    prompt_service.register(sample_targets.SAMPLE_PROMPT, actor=ACTOR)
    assert audit.events
    event = audit.events[-1]
    assert event.action == "version_prompt"
    assert event.decision is Decision.ALLOWED


def test_list_returns_every_version_of_a_named_prompt(prompt_service):
    prompt_service.register(sample_targets.SAMPLE_PROMPT, actor=ACTOR)
    prompt_service.register(
        PromptVersion(name="compliance-qa", version="v4", template="newer template"),
        actor=ACTOR,
    )
    versions = prompt_service.list("compliance-qa")
    assert {v.version for v in versions} == {"v3", "v4"}


# --------------------------------------------------------------------------- #
# ModelCardService
# --------------------------------------------------------------------------- #
def test_put_stores_and_audits_a_model_card(model_card_service, model_card_store, audit):
    card = ModelCard(
        model="gemini-3.5-flash",
        version="v3",
        intended_use="Compliance Q&A grounding evaluation.",
        metrics={"groundedness": 0.91},
        limitations=("English-only reference corpus",),
    )
    stored = model_card_service.put(card, actor=ACTOR)

    assert stored.ref == "gemini-3.5-flash@v3"
    assert model_card_service.get("gemini-3.5-flash", "v3") is not None
    assert any(e.action == "model_card" for e in audit.events)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
