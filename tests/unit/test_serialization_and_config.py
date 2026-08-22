"""Unit tests for serialization, Settings.load, and Container wiring.

* domain/serialization.to_jsonable round-trips enums (-> .value) and datetimes.
* Settings.load parses config/settings.yaml.
* Container under profile=onprem binds the on-prem placeholder adapters, and each
  bound adapter satisfies its runtime_checkable Protocol (structural parity).
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from hex_service_kit.netdefaults import ConfiguredEmptyError
from tests.fixtures import sample_targets

from model_quality_gate import ports
from model_quality_gate.config import Container, Settings, _interpolate
from model_quality_gate.domain.models import (
    AuditEvent,
    Decision,
    EvalMetricResult,
    EvalReport,
    GateDecision,
    RedTeamCategory,
    RedTeamReport,
    RedTeamResult,
    Severity,
)

CONFIG_PATH = "config/settings.yaml"
ENV_EXAMPLE = Path(".env.example")

PORT_PROTOCOLS = {
    "evaluation": ports.EvaluationPort,
    "redteam": ports.RedTeamPort,
    "prompt_registry": ports.PromptRegistryPort,
    "model_card_store": ports.ModelCardStorePort,
    "metrics_store": ports.MetricsStorePort,
    "knowledge_base": ports.KnowledgeBaseClientPort,
    "llm": ports.LLMPort,
    "audit": ports.AuditSinkPort,
    "tracer": ports.ObservabilityTracerPort,
    "registry": ports.AgentRegistryPort,
    "tool_catalog": ports.ToolCatalogPort,
}


# --------------------------------------------------------------------------- #
# to_jsonable
# --------------------------------------------------------------------------- #
def _to_jsonable():
    from model_quality_gate.domain.serialization import to_jsonable

    return to_jsonable


def test_to_jsonable_enum_becomes_value():
    to_jsonable = _to_jsonable()
    assert to_jsonable(Severity.HIGH) == "high"
    assert to_jsonable(Decision.BLOCKED) == "blocked"
    assert to_jsonable(RedTeamCategory.JAILBREAK) == "jailbreak"


def test_to_jsonable_datetime_is_json_safe_string():
    to_jsonable = _to_jsonable()
    dt = datetime(2026, 6, 20, 8, 30, tzinfo=UTC)
    out = to_jsonable(dt)
    assert isinstance(out, str)
    assert json.loads(json.dumps(out)) == out
    assert "2026-06-20" in out


def test_to_jsonable_gate_decision_roundtrips_through_json():
    to_jsonable = _to_jsonable()
    target = sample_targets.SAMPLE_TARGET
    eval_report = EvalReport(
        target=target,
        results=(EvalMetricResult(metric="groundedness", score=0.9, threshold=0.8, passed=True),),
        n_examples=2,
    )
    redteam_report = RedTeamReport(
        target=target,
        results=(
            RedTeamResult(
                case=sample_targets.SAMPLE_REDTEAM_CASES[0],
                blocked=True,
                detail="handled",
                passed=True,
            ),
        ),
    )
    decision = GateDecision(
        target=target,
        eval_report=eval_report,
        redteam_report=redteam_report,
        passed=True,
        model_card_ref="gemini-3.5-flash@v3",
        mrm_evidence_ref="mrm/gemini-3.5-flash@v3",
    )
    out = to_jsonable(decision)
    text = json.dumps(out)  # must not raise
    reloaded = json.loads(text)
    assert reloaded["passed"] is True
    assert reloaded["eval_report"]["results"][0]["metric"] == "groundedness"
    assert reloaded["redteam_report"]["results"][0]["case"]["category"] == "prompt_injection"


def test_to_jsonable_audit_event_is_worm_serialisable():
    to_jsonable = _to_jsonable()
    event = AuditEvent(
        action="gate",
        actor="model-risk",
        decision=Decision.ALLOWED,
        redacted_prompt="gate PASS for gemini-3.5-flash@v3:compliance-qa-golden",
    )
    out = to_jsonable(event)
    reloaded = json.loads(json.dumps(out))
    assert reloaded["decision"] == "allowed"
    assert reloaded["action"] == "gate"
    assert reloaded["resource"] == "ai-quality"


# --------------------------------------------------------------------------- #
# Settings.load parses config/settings.yaml
# --------------------------------------------------------------------------- #
def test_settings_load_parses_yaml():
    settings = Settings.load(CONFIG_PATH)
    assert settings.region == "us-central1"


def test_interpolation_defaults_only_when_the_variable_is_unset(monkeypatch):
    """The loader delegates to ``setting_or_default``, so an EMPTIED variable refuses.

    ``ConfiguredEmptyError`` subclasses ``RuntimeError``, not ``ValueError``: the refusal now
    comes from the one canonical helper instead of a message hand-written in this loader.
    """
    name = "AI_QUALITY_THREE_STATE_PROBE"
    monkeypatch.delenv(name, raising=False)
    assert _interpolate(f"${{{name}:-documented}}") == "documented"
    monkeypatch.setenv(name, "")
    with pytest.raises(ConfiguredEmptyError, match=name):
        _interpolate(f"${{{name}:-documented}}")
    monkeypatch.setenv(name, "reviewed")
    assert _interpolate(f"${{{name}:-documented}}") == "reviewed"


def test_interpolation_without_a_default_still_refuses_an_emptied_variable(monkeypatch):
    """``${VAR}`` with no ``:-`` is ``setting_or_default(name, "")``: emptied still refuses."""
    name = "AI_QUALITY_THREE_STATE_PROBE"
    monkeypatch.delenv(name, raising=False)
    assert _interpolate(f"${{{name}}}") == ""
    monkeypatch.setenv(name, "")
    with pytest.raises(ConfiguredEmptyError, match=name):
        _interpolate(f"${{{name}}}")


def test_configured_empty_settings_path_refuses_instead_of_loading_the_default(monkeypatch):
    monkeypatch.setenv("AI_QUALITY_SETTINGS", "")
    with pytest.raises(ValueError, match="AI_QUALITY_SETTINGS"):
        Settings.load()


def test_example_file_does_not_export_optional_values_as_configured_empty():
    active_blanks = [
        line
        for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
        if re.fullmatch(r"[A-Z][A-Z0-9_]*=\s*(?:#.*)?", line)
    ]
    assert active_blanks == [], (
        "comment optional example values out: loading NAME= configures an empty runtime value "
        f"and must refuse, it does not mean unset: {active_blanks}"
    )


def test_gcp_region_is_configurable_from_one_selector(monkeypatch):
    # One selector moves the whole deployment, but residency is not a single knob: the new
    # region must ALSO be on the reviewed allowlist, or the service refuses to start
    # (P-03; see tests/unit/test_residency_posture.py).
    monkeypatch.setenv("GCP_REGION", "europe-west4")
    monkeypatch.setenv("AI_QUALITY_ALLOWED_REGIONS", "us-central1,europe-west4")
    settings = Settings.load(CONFIG_PATH)
    assert settings.region == "europe-west4"
    assert settings.eval.location == "europe-west4"
    assert settings.models.reasoning == "gemini-3.5-flash"
    assert settings.models.triage == "gemini-3.1-flash-lite"
    assert settings.logging.retention_days == 2557
    assert set(PORT_PROTOCOLS) <= set(settings.adapters)


def test_settings_pins_models_to_allowed_ids():
    settings = Settings.load(CONFIG_PATH)
    assert settings.models.reasoning != "gemini-2.0-flash"
    assert settings.models.triage != "gemini-2.0-flash"
    assert settings.models.reasoning.startswith("gemini-3")


# --------------------------------------------------------------------------- #
# Container binds on-prem adapters under profile=onprem, with structural parity.
# --------------------------------------------------------------------------- #
def _onprem_settings() -> Settings:
    settings = Settings.load(CONFIG_PATH)
    return Settings(
        project_id=settings.project_id,
        region=settings.region,
        profile="onprem",
        kms_key=settings.kms_key,
        models=settings.models,
        eval=settings.eval,
        bigquery=settings.bigquery,
        storage=settings.storage,
        logging=settings.logging,
        agent_engine=settings.agent_engine,
        adapters=settings.adapters,
    )


def test_container_binds_onprem_adapters_with_protocol_parity():
    container = Container(_onprem_settings())
    for port_name, protocol in PORT_PROTOCOLS.items():
        adapter = getattr(container, port_name)
        assert isinstance(adapter, protocol), (
            f"on-prem adapter for '{port_name}' is not structurally a {protocol.__name__}"
        )


def test_container_falls_back_to_gcp_binding_when_profile_missing():
    settings = _onprem_settings()
    binding = settings.adapters["audit"]
    assert binding["onprem"].endswith("OnPremAuditAdapter")
    assert "gcp" in binding  # gcp is always present as the primary/fallback


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
