"""Built-in synthetic reference corpus for the ``local`` profile.

A tiny, clearly-fictional set of compliance control-reference passages (with page-level
citations) so the local knowledge-base adapter has reference context to ground evaluation
on out of the box, and the end-to-end CLI gate run scores against a real grounded corpus
with no external A2 service. The text is invented; the source ids / titles are plausible
but fictional and must not be treated as real control references.

The corpus covers the source ids and expected points of the bundled golden dataset
``eval/datasets/compliance-qa-golden.jsonl`` so a default ``ai-quality gate ...
compliance-qa-golden`` run is a genuine, grounded PASS offline. The first two entries also
mirror ``tests/fixtures/sample_targets.SAMPLE_CITATIONS`` so the adapters and the
unit-test fixtures share one deterministic corpus, but this lives under ``src`` (not
``tests``) so the shipped package can seed itself without importing the test tree.
"""

from __future__ import annotations

from ...domain.models import Citation

# A small, deterministic reference corpus. Page numbers are required for provenance, and
# each snippet contains the key terms of its golden example's expected points so the local
# scorer grounds them by token overlap.
SEED_CITATIONS: tuple[Citation, ...] = (
    Citation(
        source_id="kb-cloud-outsourcing",
        title="Cloud Outsourcing Control Reference",
        url="https://example.test/kb/cloud-outsourcing",
        page=12,
        snippet=(
            "Conduct provider due diligence before onboarding a public cloud provider, "
            "maintain a documented exit strategy, and retain audit rights over the "
            "provider covering data residency and concentration risk."
        ),
        score=0.91,
        acl_tags=("compliance",),
    ),
    Citation(
        source_id="kb-operational-resilience",
        title="Operational Resilience Control Reference",
        url="https://example.test/kb/op-resilience",
        page=4,
        snippet=(
            "Set tolerance levels for disruption to critical operations, and test business "
            "continuity against severe but plausible scenarios on a regular basis."
        ),
        score=0.84,
        acl_tags=("compliance",),
    ),
    Citation(
        source_id="kb-information-security",
        title="Information Security Control Reference",
        url="https://example.test/kb/information-security",
        page=9,
        snippet=(
            "Maintain a security capability proportionate to the threat, test control "
            "effectiveness regularly, and notify the regulator of material security "
            "incidents without undue delay."
        ),
        score=0.86,
        acl_tags=("compliance",),
    ),
    Citation(
        source_id="kb-genai-governance",
        title="Generative AI Governance Control Reference",
        url="https://example.test/kb/genai-governance",
        page=3,
        snippet=(
            "Establish board and senior management accountability for generative AI, keep "
            "a human in the loop for high-impact customer decisions, and manage "
            "third-party model risk through validation and monitoring."
        ),
        score=0.83,
        acl_tags=("compliance",),
    ),
    Citation(
        source_id="kb-shared-responsibility",
        title="Cloud Shared-Responsibility Control Reference",
        url="https://example.test/kb/shared-responsibility",
        page=6,
        snippet=(
            "Document the cloud shared-responsibility model: distinguish provider "
            "responsibilities from customer responsibilities, and record that the customer "
            "remains accountable for its data and configuration."
        ),
        score=0.80,
        acl_tags=("compliance",),
    ),
)
