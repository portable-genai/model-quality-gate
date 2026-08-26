"""Online quality measurement: the drift read, and the re-gate it can require.

`MetricsStorePort.drift(model)` computed banded drift signals from the day it was written
and **nothing in a served process ever called it**. Every call site was a test. The design
note handed the wiring to the reader ("Wire these into your model-risk dashboard"), so an
`alert` was a value returned to nobody: the one measurement that can tell an operator a
passed model has since decayed reached no operator, no route and no CLI.

This file is the standing guard for the two halves that closed that, and for the shape of
the escalation, which is where the danger is. The rules it fixes:

* an `alert` requires the target to be RE-GATED, and the requirement is stated, never
  acted on. Nothing on this path promotes or demotes;
* escalation only ever raises the bar. Adding a worse signal never makes the requirement
  weaker;
* **no signal is not a stable signal.** A model with nothing recorded is `unmeasured`, and
  unmeasured escalates. Reporting calm over zero observations is the exact shape of every
  false-green in this organization's history;
* a status this policy does not recognise is not read as the calm end of the scale;
* the assessment is audited, and a failure to record it withholds it.

The escalating half is deliberately narrower than the measuring half: what remains
UNBUILT is the live-traffic sampler that would write production inference outcomes into
the metrics table, and the scheduled re-scorer that would act on a `requires_re_gate`.
Both need live traffic and neither is stubbed here. What this file proves is that a drift
reading which DOES exist reaches an operator and raises the bar correctly.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from tests.conftest import LOOPBACK_PEER, make_local_settings
from typer.testing import CliRunner

from model_quality_gate.adapters.local.metrics_store import LocalMetricsStoreAdapter
from model_quality_gate.api import deps
from model_quality_gate.api.app import app
from model_quality_gate.config import Container, LocalSettings, Settings
from model_quality_gate.domain.drift import (
    ALERT,
    ALERT_BAND,
    STABLE,
    UNMEASURED,
    UNRECOGNISED,
    WARNING,
    WARNING_BAND,
    DriftRegatePolicy,
    classify_drift,
)
from model_quality_gate.domain.drift_service import DriftMonitorService
from model_quality_gate.domain.errors import AssurancePersistenceError
from model_quality_gate.domain.models import (
    DriftSignal,
    EvalMetricResult,
    EvalReport,
    EvalTarget,
)

MODEL = "gemini-3.5-flash"


def signal(metric: str, status: str, drift: float = 0.0) -> DriftSignal:
    """A drift signal with a chosen status, for policy-level tests."""
    return DriftSignal(
        model=MODEL, metric=metric, baseline=0.9, current=0.9 + drift, drift=drift, status=status
    )


def _settings_with_real_bindings() -> Settings:
    """The shipped port->adapter bindings, pointed at ephemeral in-memory SQLite."""
    base = Settings.load("config/settings.yaml")
    return replace(
        base,
        profile="local",
        local=LocalSettings(
            db_path=":memory:",
            audit_path=":memory:",
            registry_path=":memory:",
            model_cards_path=":memory:",
            metrics_path=":memory:",
        ),
    )


def record(store: LocalMetricsStoreAdapter, metric: str, score: float) -> None:
    """Append one metric observation to the local metrics store."""
    store.record(
        EvalReport(
            target=EvalTarget(model=MODEL, prompt_version="v3", dataset_id="ds"),
            results=(EvalMetricResult(metric=metric, score=score, threshold=0.8, passed=True),),
            n_examples=3,
        )
    )


# --------------------------------------------------------------------------- #
# 1. The bands: one definition, shared by the SQLite and BigQuery stores.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("current", "expected"),
    [
        (0.9, STABLE),
        (0.9 - WARNING_BAND + 0.001, STABLE),  # just inside the calm band
        (0.9 - WARNING_BAND, WARNING),  # the warning band is INCLUSIVE at its edge
        (0.9 - ALERT_BAND + 0.001, WARNING),
        (0.9 - ALERT_BAND, ALERT),  # so is the alert band
        (0.9 + ALERT_BAND, ALERT),  # a large IMPROVEMENT is suspicious too
    ],
)
def test_bands_are_inclusive_at_their_edge(current: float, expected: str) -> None:
    """A metric exactly ON a band edge takes the STRICTER band, not the calmer one."""
    assert classify_drift(MODEL, "groundedness", 0.9, current).status == expected


def test_the_sqlite_store_bands_through_the_same_domain_function() -> None:
    """The adapter owns the query; the domain owns the judgement. One definition."""
    store = LocalMetricsStoreAdapter(make_local_settings())
    # Two observations, so the mean baseline is 0.90 and the latest is 0.85: drift is
    # exactly -0.05, sitting ON the warning edge, which is where an off-by-one shows up.
    for score in (0.95, 0.85):
        record(store, "groundedness", score)
    (produced,) = store.drift(MODEL)
    assert produced == classify_drift(MODEL, "groundedness", produced.baseline, produced.current)
    assert produced.status == WARNING


# --------------------------------------------------------------------------- #
# 2. The escalation policy: pure, and it only ever raises the bar.
# --------------------------------------------------------------------------- #
def test_an_alert_requires_a_re_gate() -> None:
    escalation = DriftRegatePolicy().assess(MODEL, [signal("groundedness", ALERT, -0.3)])
    assert escalation.status == ALERT
    assert escalation.requires_re_gate is True
    assert escalation.requires_human_review is True
    assert escalation.escalating_metrics == ("groundedness",)
    assert any("re-run the promotion gate" in reason for reason in escalation.reasons)


def test_a_warning_is_reviewed_without_demanding_a_re_gate() -> None:
    """The ladder is graded. A warning buys a pair of eyes, not a full re-run."""
    escalation = DriftRegatePolicy().assess(MODEL, [signal("faithfulness", WARNING, -0.06)])
    assert escalation.status == WARNING
    assert escalation.requires_re_gate is False
    assert escalation.requires_human_review is True


def test_stable_signals_require_nothing() -> None:
    escalation = DriftRegatePolicy().assess(
        MODEL, [signal("groundedness", STABLE), signal("safety", STABLE)]
    )
    assert escalation.status == STABLE
    assert escalation.requires_re_gate is False
    assert escalation.requires_human_review is False
    assert escalation.escalating_metrics == ()


def test_no_signal_is_not_a_stable_signal() -> None:
    """Zero observations is UNMEASURED and escalates. Calm over nothing is not calm.

    This is the false-green shape: a model nobody ever measured looked exactly like a
    model measured and found healthy, and the healthier-looking one was the one with no
    evidence behind it at all.
    """
    escalation = DriftRegatePolicy().assess(MODEL, [])
    assert escalation.status == UNMEASURED
    assert escalation.requires_re_gate is True
    assert escalation.requires_human_review is True
    assert escalation.signals == ()


def test_an_unrecognised_status_is_not_read_as_stable() -> None:
    """``DriftSignal.status`` is an open ``str``; an unknown value must fail closed."""
    escalation = DriftRegatePolicy().assess(
        MODEL, [signal("groundedness", STABLE), signal("safety", "catastrophic")]
    )
    assert escalation.status == UNRECOGNISED
    assert escalation.requires_re_gate is True
    assert escalation.requires_human_review is True
    assert "safety" in escalation.escalating_metrics


def test_adding_a_worse_signal_never_lowers_the_requirement() -> None:
    """Monotonicity, over every subset of a fixed set: escalation only raises the bar."""
    policy = DriftRegatePolicy()
    base = [signal("groundedness", STABLE), signal("faithfulness", WARNING, -0.06)]
    worse = signal("safety", ALERT, -0.4)
    for size in range(len(base) + 1):
        subset = base[:size]
        before = policy.assess(MODEL, subset)
        after = policy.assess(MODEL, [*subset, worse])
        assert after.requires_re_gate >= before.requires_re_gate
        assert after.requires_human_review >= before.requires_human_review


def test_the_policy_is_pure_and_replayable() -> None:
    """Same signals in, identical escalation out. No clock, no store, no model."""
    signals = [signal("groundedness", ALERT, -0.3), signal("safety", STABLE)]
    policy = DriftRegatePolicy()
    assert policy.assess(MODEL, signals) == policy.assess(MODEL, list(signals))


# --------------------------------------------------------------------------- #
# 3. The service: audited evidence, and no promotion path to reach for.
# --------------------------------------------------------------------------- #
@pytest.fixture
def drift_service(metrics_store, tracer, audit) -> DriftMonitorService:
    return DriftMonitorService(metrics_store, tracer, audit)


def test_an_alerting_read_escalates_and_executes_no_promotion(
    drift_service, metrics_store, audit
) -> None:
    """The whole point of the invariant: an alert raises the bar and nothing else.

    The audit trail is where a promotion would be visible. A gate run writes `evaluate`,
    `redteam` and `gate` events through this same sink, so a service that "handled" an
    alert by re-running the gate itself cannot hide from this assertion.
    """
    for score in (1.0, 1.0, 0.5):
        record(metrics_store, "groundedness", score)

    escalation = drift_service.assess(MODEL, actor="mrm.officer@bank.example")

    assert escalation.requires_re_gate is True
    assert [event.action for event in audit.events] == ["drift"]
    assert audit.events[-1].decision.value == "escalated"
    assert audit.events[-1].metadata["escalating_metrics"] == "groundedness"


def test_a_calm_read_is_still_recorded(drift_service, metrics_store, audit) -> None:
    """Evidence for the calm case too, so 'nothing happened' is provable."""
    for score in (0.9, 0.9):
        record(metrics_store, "groundedness", score)

    escalation = drift_service.assess(MODEL, actor="mrm.officer@bank.example")

    assert escalation.requires_human_review is False
    assert [event.action for event in audit.events] == ["drift"]
    assert audit.events[-1].decision.value == "allowed"


def test_a_failed_audit_write_withholds_the_escalation(metrics_store, tracer) -> None:
    """An escalation nobody can prove was raised has not been raised."""

    class BrokenAudit:
        def record(self, event: object) -> str:
            raise RuntimeError("WORM sink unreachable")

    service = DriftMonitorService(metrics_store, tracer, BrokenAudit())
    with pytest.raises(AssurancePersistenceError):
        service.assess(MODEL, actor="mrm.officer@bank.example")


def test_the_wired_service_holds_no_promotion_path() -> None:
    """By construction, not by convention: what the API wires up cannot promote.

    Asserted on the service the WIRING builds, never on a hand-made one. Handing the drift
    monitor a gate service or an evidence store is a change in ``api/deps.py``, and a test
    that constructs its own subject would be blind to exactly that change.
    """
    service = deps.build_drift_service(Container(_settings_with_real_bindings()))
    held = vars(service).values()
    assert not any(hasattr(dependency, "gate") for dependency in held)
    assert not any(hasattr(dependency, "put_evidence") for dependency in held)


# --------------------------------------------------------------------------- #
# 4. The served surface.
# --------------------------------------------------------------------------- #
@pytest.fixture
def client(monkeypatch, metrics_store, tracer, audit) -> Iterator[TestClient]:
    """A TestClient whose drift service reads an ephemeral, seeded metrics store."""
    monkeypatch.setenv("AI_QUALITY_PROFILE", "local")
    deps.get_container.cache_clear()
    app.dependency_overrides[deps.get_drift_service] = lambda: DriftMonitorService(
        metrics_store, tracer, audit
    )
    yield TestClient(app, client=LOOPBACK_PEER)
    app.dependency_overrides.clear()
    deps.get_container.cache_clear()


def test_the_route_serves_the_escalation_and_its_signals(client, metrics_store) -> None:
    for score in (1.0, 1.0, 0.5):
        record(metrics_store, "groundedness", score)

    response = client.get(f"/v1/drift/{MODEL}")

    assert response.status_code == 200
    body = response.json()
    assert body["model"] == MODEL
    assert body["status"] == ALERT
    assert body["requires_re_gate"] is True
    assert body["requires_human_review"] is True
    assert body["escalating_metrics"] == ["groundedness"]
    assert body["schema_version"] == "drift-escalation/v1"
    assert body["signals"][0]["metric"] == "groundedness"
    # No approval anywhere in the response: a drift read is never a verdict.
    assert "passed" not in body


def test_an_unmeasured_model_is_200_unmeasured_and_never_a_silent_calm(client) -> None:
    """A poller must tell 'no evidence' from 'evidence that looks fine'."""
    response = client.get("/v1/drift/never-evaluated-model")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == UNMEASURED
    assert body["requires_re_gate"] is True
    assert body["signals"] == []


def test_the_route_resolves_the_actor_and_never_accepts_one(client, audit) -> None:
    """Identity is resolved server-side; the audit actor is the resolved principal."""
    response = client.get(
        f"/v1/drift/{MODEL}",
        headers={"X-Dev-Persona": "auditor"},
        params={"actor": "attacker@evil.example"},
    )

    assert response.status_code == 200
    assert audit.events[-1].actor == "demo.auditor@bank.example"


def test_an_unknown_persona_is_refused(client) -> None:
    response = client.get(f"/v1/drift/{MODEL}", headers={"X-Dev-Persona": "nobody"})
    assert response.status_code == 401


def test_the_route_requires_the_service_caller_ring(client, monkeypatch) -> None:
    """The drift read is a non-health route, so S2S auth applies to it like every other."""
    monkeypatch.setenv("AI_QUALITY_S2S_TOKEN", "s3cret-for-the-test")

    assert client.get(f"/v1/drift/{MODEL}").status_code == 401
    allowed = client.get(
        f"/v1/drift/{MODEL}", headers={"Authorization": "Bearer s3cret-for-the-test"}
    )
    assert allowed.status_code == 200


# --------------------------------------------------------------------------- #
# 5. The operator's other surface: the CLI.
# --------------------------------------------------------------------------- #
@pytest.fixture
def cli(monkeypatch, metrics_store, tracer, audit):
    """The Typer app with its drift wiring pointed at an ephemeral metrics store."""
    from model_quality_gate.cli.main import app as cli_app

    monkeypatch.setattr(
        deps,
        "build_drift_service",
        lambda container: DriftMonitorService(metrics_store, tracer, audit),
    )
    return CliRunner(), cli_app


def test_the_cli_exits_non_zero_when_a_re_gate_is_owed(cli, metrics_store) -> None:
    """A monitor can page on the exit code. The exit code is a SIGNAL, not an action."""
    runner, cli_app = cli
    for score in (1.0, 1.0, 0.5):
        record(metrics_store, "groundedness", score)

    result = runner.invoke(cli_app, ["drift", MODEL])

    assert result.exit_code == 1
    assert "RE-GATE REQUIRED" in result.output
    assert "promotes nothing and demotes nothing" in result.output


def test_the_cli_exits_zero_on_a_calm_reading(cli, metrics_store) -> None:
    runner, cli_app = cli
    for score in (0.9, 0.9):
        record(metrics_store, "groundedness", score)

    result = runner.invoke(cli_app, ["drift", MODEL])

    assert result.exit_code == 0
    assert "RE-GATE REQUIRED" not in result.output


def test_the_cli_does_not_report_an_unmeasured_model_as_calm(cli) -> None:
    runner, cli_app = cli
    result = runner.invoke(cli_app, ["drift", "never-evaluated-model"])

    assert result.exit_code == 1
    assert "UNMEASURED" in result.output
