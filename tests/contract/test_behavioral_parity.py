"""Behavioral parity: the same request through every implementation of a port.

The structural contract suite (``test_port_parity``) proves every adapter *satisfies*
its Protocol. This suite proves the stronger claim behind the no-lock-in promise
(P-02): for one canonical request, every SDK-free implementation of a port behaves
identically at the boundary, and the migration placeholder fails fast rather than ever
returning a silent wrong answer.

Hrz4 is the eval / model-risk promotion AUTHORITY, not a customer-facing agent: it
evaluates models against datasets and processes no customer PII. It consumes two platform
siblings over real HTTP clients (``config/settings.yaml``): the **Hrz2** Enterprise KB for
grounded reference retrieval and the **Hrz5** observability service for the WORM audit
sink. Those two ports have a real ``platform`` implementation, so for each we put the SAME
request through ``local`` and ``platform`` and require identical domain-level behavior:

* ``knowledge_base`` (KnowledgeBaseClientPort -> Hrz2): the local FTS5 index and the
  ``platform`` httpx client (respx-mocked at the documented ``/v1/search`` contract) return
  the SAME first-class :class:`Citation` objects for one query; a local re-run over a fresh
  in-memory index is identical (determinism); ``onprem`` raises.
* ``audit`` (AuditSinkPort -> Hrz5): the local hash-chained store reads back exactly the
  serialized :class:`AuditEvent`, and the ``platform`` client POSTs a byte-identical body
  to ``/v1/audit`` (respx-mocked); ``onprem`` raises.

The ``evaluation`` port (the deterministic eval scorer) has no platform sibling
(``gcp`` needs the Google Cloud SDK, ``onprem`` is a placeholder), so parity is proven the
way this repo can prove it offline: the ``local`` scorer is byte-identical across re-runs,
and ``onprem`` fails fast.

Plus the end-to-end proof: the primary eval-gate pipeline (``EvaluationService.evaluate``:
a golden dataset -> an ``EvalReport``) runs deterministically under ``local`` and fails
fast under ``onprem`` with **zero domain edits**, only a profile change.

Runs fully offline (``AI_QUALITY_PROFILE=local pytest``): the horizontal-platform
endpoints are mocked with respx and never actually served. All data is obviously
fictional.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest
import respx
from tests.fixtures import sample_targets

from model_quality_gate.config import Container, LocalSettings, Settings, instantiate
from model_quality_gate.domain.models import AuditEvent, Citation, Decision, EvalTarget
from model_quality_gate.domain.serialization import to_jsonable

CONFIG_PATH = "config/settings.yaml"

# The platform clients' localhost defaults (SPEC contract): mocked, never actually served.
# These MUST match the ``_DEFAULT_URL`` / env-var defaults hard-coded in the remote_* adapters.
KNOWLEDGE_BASE = "http://localhost:8082"  # remote_knowledge_base -> /v1/search
OBSERVABILITY = (
    "http://localhost:8085"  # remote_audit (OBSERVABILITY_URL) -> Hrz5 /v1/audit
)


def _settings(profile: str) -> Settings:
    """Settings for ``profile`` with every local store pinned to ephemeral in-memory SQLite."""
    base = Settings.load(CONFIG_PATH)
    return replace(
        base,
        profile=profile,
        local=LocalSettings(
            db_path=":memory:",
            audit_path=":memory:",
            registry_path=":memory:",
            model_cards_path=":memory:",
            metrics_path=":memory:",
            datasets_path=":memory:",
        ),
    )


def _adapter(port: str, profile: str) -> Any:
    settings = _settings(profile)
    return instantiate(settings.adapters[port][profile], settings)


def _passage_json(citation: Citation) -> dict[str, Any]:
    """Render a :class:`Citation` into the Hrz2 ``/v1/search`` passage shape (SPEC §6).

    The remote adapter's ``_parse_passages`` reads ``{text, citation{...}, score, acl_tags}``,
    so the sibling must serve exactly that shape. Feeding the local adapter's own output back
    through this mapping is what makes ``platform == local`` a real boundary-equality claim.
    """
    return {
        "text": citation.snippet,
        "citation": {
            "source_id": citation.source_id,
            "title": citation.title,
            "url": citation.url,
            "page": citation.page,
        },
        "score": citation.score,
        "acl_tags": list(citation.acl_tags),
    }


# --------------------------------------------------------------------------- #
# KnowledgeBaseClientPort (Hrz2) : identical citations whether local or platform
# --------------------------------------------------------------------------- #
def test_knowledge_base_parity_same_citations_across_implementations():
    """One query -> the SAME first-class Citation objects from local FTS5 and the Hrz2 client."""
    query = "cloud outsourcing due diligence provider tolerance operations"

    # local: seed a known fictional corpus for a deterministic result, then retrieve.
    local_kb = _adapter("knowledge_base", "local")
    local_kb.seed(sample_targets.SAMPLE_CITATIONS)
    local_citations = local_kb.retrieve(query, top_k=5)
    assert local_citations, "local FTS5 knowledge base returned nothing for the seeded corpus"
    assert any(c.page is not None for c in local_citations), "page-level citation required"

    with respx.mock:
        # Hrz2 serves the SAME passages for the same query at the documented /v1/search shape.
        respx.post(f"{KNOWLEDGE_BASE}/v1/search").respond(
            200, json={"passages": [_passage_json(c) for c in local_citations]}
        )
        remote_citations = _adapter("knowledge_base", "platform").retrieve(query, top_k=5)

    # Not merely the same shape: the same first-class domain objects either way.
    assert remote_citations == local_citations

    # A local re-run over a fresh in-memory index yields identical citations (determinism):
    # the FTS5 index is a derived asset that rebuilds from the same seed.
    rerun_kb = _adapter("knowledge_base", "local")
    rerun_kb.seed(sample_targets.SAMPLE_CITATIONS)
    assert rerun_kb.retrieve(query, top_k=5) == local_citations

    with pytest.raises(NotImplementedError):
        _adapter("knowledge_base", "onprem").retrieve(query, top_k=5)


# --------------------------------------------------------------------------- #
# AuditSinkPort (Hrz5) : byte-identical record shape at every sink boundary
# --------------------------------------------------------------------------- #
def test_audit_parity_identical_payload_at_every_sink():
    """The local WORM store and the Hrz5 client see byte-identical audit payloads."""
    event = AuditEvent(
        action="gate",
        actor="eval-bot@bank.test (FICTIONAL)",
        decision=Decision.ESCALATED,
        redacted_prompt="promotion gate on gemini-3.7-flash@v3:compliance-qa-golden (FICTIONAL)",
        redacted_response="gemini-3.7-flash@v3:compliance-qa-golden",
        citations=(
            Citation(
                source_id="kb-cloud-outsourcing",
                title="Cloud Outsourcing Control Reference (FICTIONAL)",
                page=12,
            ),
        ),
        metadata={"target": "gemini-3.7-flash@v3:compliance-qa-golden", "n_examples": "2"},
        event_id="audit-parity-event",
    )
    expected = to_jsonable(event)

    # local hash-chained WORM stand-in: the stored record equals the serialized event.
    local_audit = _adapter("audit", "local")
    local_audit.record(event)
    assert local_audit.read_all() == [expected]

    # platform sink (Hrz5 observability): the POSTed body is byte-identical to what local stored.
    with respx.mock:
        route = respx.post(f"{OBSERVABILITY}/v1/audit").respond(
            202, json={"status": "accepted", "event_id": event.event_id}
        )
        _adapter("audit", "platform").record(event)
        posted = json.loads(route.calls.last.request.content)
    assert posted == expected, "platform sink received a different record than local stored"

    with pytest.raises(NotImplementedError):
        _adapter("audit", "onprem").record(event)


# --------------------------------------------------------------------------- #
# EvaluationPort : no platform sibling, so prove local determinism + onprem fail-fast
# --------------------------------------------------------------------------- #
def test_evaluation_scorer_is_deterministic_and_onprem_fails_fast():
    """The deterministic local scorer returns byte-identical scores across re-runs.

    ``gcp`` needs the Google Cloud SDK and there is no ``platform`` evaluator (Hrz4 IS the
    eval authority, it does not call a sibling to evaluate), so behavioral parity for this
    port is the offline claim this repo can make: the same request scored twice is
    indistinguishable, and the migration placeholder never waves a model through unevaluated.
    """
    target: EvalTarget = sample_targets.SAMPLE_TARGET
    dataset = sample_targets.SAMPLE_DATASET
    metrics = ["groundedness", "citation_accuracy", "safety"]

    scores_a = _adapter("evaluation", "local").score(target, dataset, metrics)
    scores_b = _adapter("evaluation", "local").score(target, dataset, metrics)

    assert set(scores_a) == set(metrics)
    assert all(0.0 <= v <= 1.0 for v in scores_a.values())
    # Byte-identical at the boundary on a re-run (same seed corpus, deterministic scorer).
    assert scores_a == scores_b
    assert json.dumps(scores_a, sort_keys=True) == json.dumps(scores_b, sort_keys=True)

    with pytest.raises(NotImplementedError):
        _adapter("evaluation", "onprem").score(target, dataset, metrics)


# --------------------------------------------------------------------------- #
# End to end: one profile line swaps the whole stack, domain untouched
# --------------------------------------------------------------------------- #
def test_full_eval_pipeline_local_is_deterministic_and_onprem_fails_fast():
    """The eval-gate pipeline is deterministic on local and fails fast on onprem."""
    from model_quality_gate.api.deps import build_evaluation_service

    target = sample_targets.SAMPLE_TARGET
    dataset = sample_targets.SAMPLE_DATASET

    report_a = build_evaluation_service(Container(_settings("local"))).evaluate(
        target, dataset, actor="parity@test"
    )
    report_b = build_evaluation_service(Container(_settings("local"))).evaluate(
        target, dataset, actor="parity@test"
    )

    assert report_a.results, "offline evaluation must produce scored metric rows"
    assert report_a.passed is True, "the seeded corpus grounds the golden set to a real PASS"
    # Scores and replay inputs are deterministic; each execution still gets a unique run id.
    assert report_a.run_id != report_b.run_id
    assert report_a.results == report_b.results
    assert report_a.dataset_digest == report_b.dataset_digest
    assert report_a.dataset_version == report_b.dataset_version

    with pytest.raises(NotImplementedError):
        build_evaluation_service(Container(_settings("onprem"))).evaluate(
            target, dataset, actor="parity@test"
        )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
