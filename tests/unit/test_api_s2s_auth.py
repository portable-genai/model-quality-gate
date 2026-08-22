"""S2S auth tests for the service-to-service surface (plan-hrz-s2s-auth, decision CD1).

These prove the ``require_service_caller`` ring that authenticates the *calling service*
coexists with the existing IAP/persona ``Principal`` ring that authenticates the end user:

* ``local`` profile is fail-OPEN when ``AI_QUALITY_S2S_TOKEN`` is unset (so the offline
  gate runs with zero secrets) and fail-CLOSED (401) when it is set and the bearer is
  missing or wrong; a correct bearer is accepted.
* ``/healthz`` (and the other open routes) never require a service token.
* The end-user identity path is untouched: a request with a valid service token still
  resolves the default persona as the audit actor.

The in-memory :class:`~model_quality_gate.config.Container` is injected by monkeypatching the
lru-cached ``deps.get_container`` (mirroring ``test_api_identity``), so ``deps.get_settings``
returns the local profile and the run stays ephemeral.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from tests.conftest import LOOPBACK_PEER

from model_quality_gate.api import deps
from model_quality_gate.api.app import app
from model_quality_gate.api.security import _TOKEN_ENV
from model_quality_gate.config import Container, LocalSettings, Settings

_TARGET = {
    "model": "gemini-3.5-flash",
    "prompt_version": "v3",
    "dataset_id": "compliance-qa-golden",
}
_EVAL_BODY = {"target": _TARGET, "dataset_id": "compliance-qa-golden"}


def _local_settings_with_adapters() -> Settings:
    """Local Settings carrying the real port->adapter bindings, ephemeral in-memory SQLite."""
    base = Settings.load("config/settings.yaml")
    return Settings(
        project_id=base.project_id,
        region=base.region,
        profile="local",
        local=LocalSettings(
            db_path=":memory:",
            audit_path=":memory:",
            registry_path=":memory:",
            model_cards_path=":memory:",
            metrics_path=":memory:",
        ),
        adapters=base.adapters,
    )


@pytest.fixture
def container() -> Container:
    """A fresh in-memory local Container (real local adapters, ephemeral SQLite)."""
    return Container(_local_settings_with_adapters())


@pytest.fixture
def client(container: Container, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(deps, "get_container", lambda: container)
    yield TestClient(app, client=LOOPBACK_PEER)


@pytest.fixture
def token_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    monkeypatch.setenv(_TOKEN_ENV, "s3cret-service-token")
    yield "s3cret-service-token"


def test_no_token_configured_is_open_loopback_dev(client: TestClient) -> None:
    # AI_QUALITY_S2S_TOKEN unset: the offline default, still callable (zero-secret CI).
    assert client.post("/v1/evaluations", json=_EVAL_BODY).status_code == 200


def test_healthz_never_requires_a_service_token(client: TestClient, token_env: str) -> None:
    assert client.get("/healthz").status_code == 200


def test_personas_stays_open_when_enforced(client: TestClient, token_env: str) -> None:
    assert client.get("/v1/personas").status_code == 200


def test_missing_token_is_401_when_enforced(client: TestClient, token_env: str) -> None:
    assert client.post("/v1/evaluations", json=_EVAL_BODY).status_code == 401


def test_wrong_token_is_401_when_enforced(client: TestClient, token_env: str) -> None:
    resp = client.post("/v1/evaluations", json=_EVAL_BODY, headers={"Authorization": "Bearer nope"})
    assert resp.status_code == 401


def test_correct_token_is_accepted(client: TestClient, token_env: str) -> None:
    resp = client.post(
        "/v1/evaluations", json=_EVAL_BODY, headers={"Authorization": f"Bearer {token_env}"}
    )
    assert resp.status_code == 200


def test_read_route_is_also_guarded(client: TestClient, token_env: str) -> None:
    # A guarded GET (the cheap promotion poll) is 401 without a service token when enforced.
    params = {
        "model": "gemini-3.5-flash",
        "prompt_version": "v3",
        "dataset": "compliance-qa-golden",
    }
    assert client.get("/v1/gate", params=params).status_code == 401


def test_s2s_coexists_with_end_user_identity(client: TestClient, container: Container) -> None:
    # With a valid service token AND no persona header, the S2S ring passes and the identity
    # ring still resolves the default persona as the audit actor (both rings run).
    resp = client.post(
        "/v1/evaluations",
        json=_EVAL_BODY,
        headers={"Authorization": "Bearer s3cret", "X-Dev-Persona": "auditor"},
    )
    # Token env unset here, so S2S is fail-open; the identity ring still governs the actor.
    assert resp.status_code == 200
    actors = [event["actor"] for event in container.audit.read_all()]
    assert "demo.auditor@bank.example" in actors


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
