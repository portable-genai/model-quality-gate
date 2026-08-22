"""Unit tests for the import-safe wiring layers (API, agent card, datasets).

These prove that importing the FastAPI app, the agent card, and the dataset loaders
never requires a Google Cloud SDK (the on-prem/test profile), and that the API surface
projects the domain artifacts correctly through an in-process client.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from tests.conftest import LOOPBACK_PEER

from model_quality_gate.api import deps
from model_quality_gate.api.app import _capability_manifest, app
from model_quality_gate.config import Settings
from model_quality_gate.pipelines.datasets import (
    load_golden_dataset,
    standard_redteam_cases,
)


@pytest.fixture
def client(monkeypatch) -> TestClient:
    # Force the SDK-free laptop profile so capability claims exercise the real demo wiring.
    monkeypatch.setenv("AI_QUALITY_PROFILE", "local")
    deps.get_container.cache_clear()
    return TestClient(app, client=LOOPBACK_PEER)


def test_healthz_reports_profile_and_region(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["region"] == "us-central1"
    assert body["demo_only"] is True
    assert body["production_ready"] is False


def test_local_capability_manifest_is_functional_but_not_attested(client):
    response = client.get("/v1/capabilities")
    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "capability-manifest/v1"
    assert body["portable_core"] is True
    assert body["demo_only"] is True
    assert body["production_ready"] is False
    assert all(item["available"] for item in body["capabilities"])
    assert {item["assurance"] for item in body["capabilities"]} == {"demo-only"}


def test_partial_managed_configuration_never_fans_one_attestation_across_controls(
    monkeypatch,
):
    settings = replace(Settings.load("config/settings.yaml"), profile="gcp")
    monkeypatch.setattr(deps, "get_settings", lambda: settings)
    monkeypatch.setenv(
        "AI_QUALITY_EVALUATION_ATTESTATION_REF",
        "projects/demo/locations/us-central1/evaluations/attestation-1",
    )
    monkeypatch.delenv("HRZ_OBSERVABILITY_URL", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)

    manifest = _capability_manifest()
    by_name = {item.name: item for item in manifest.capabilities}

    assert by_name["evaluation"].assurance == "attested"
    assert by_name["immutable-audit"].available is False
    assert by_name["trace-correlation"].available is False
    assert manifest.production_ready is False


def test_agent_card_advertises_the_four_skills(client):
    resp = client.get("/.well-known/agent-card.json")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "model-quality-gate"
    skill_ids = {s["id"] for s in body["skills"]}
    assert skill_ids == {"evaluate", "red_team", "promotion_gate", "version_prompt"}


def test_dataset_loader_reads_bundled_golden_set():
    dataset = load_golden_dataset("compliance-qa-golden")
    assert dataset.id == "compliance-qa-golden"
    assert dataset.n_examples >= 1
    assert all(ex.input for ex in dataset.examples)


def test_dataset_loader_missing_id_is_empty_not_an_error():
    dataset = load_golden_dataset("does-not-exist")
    assert dataset.n_examples == 0


def test_standard_redteam_cases_cover_every_category():
    from model_quality_gate.domain.models import RedTeamCategory

    cases = standard_redteam_cases()
    categories = {c.category for c in cases}
    assert categories == set(RedTeamCategory)


def test_standard_redteam_cases_filterable():
    cases = standard_redteam_cases(["jailbreak"])
    assert len(cases) == 1
    assert cases[0].category.value == "jailbreak"


def test_agent_tools_import_without_adk():
    # The plain tool callables must import with no google-adk installed.
    from model_quality_gate.agent import tools

    names = {fn.__name__ for fn in tools.TOOL_FUNCTIONS}
    assert names == {"evaluate", "red_team", "promotion_gate", "version_prompt"}


def test_root_agent_module_imports_without_adk():
    # Importing the module (and touching the lazy root_agent name) must not need ADK.
    from model_quality_gate.agent import root_agent

    assert root_agent.ROOT_AGENT_NAME == "model_quality_gate_model_risk"


def test_settings_default_profile_is_local_when_unset(monkeypatch):
    monkeypatch.delenv("AI_QUALITY_PROFILE", raising=False)
    settings = Settings.load("config/settings.yaml")
    assert settings.profile == "local"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
