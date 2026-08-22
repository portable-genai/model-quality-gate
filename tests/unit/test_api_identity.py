"""API-level tests for server-side identity enforcement.

Prove that the FastAPI boundary resolves the audit actor from a verified
:class:`~model_quality_gate.domain.identity.Principal` (never a client-supplied ``actor``):

* an unknown ``X-Dev-Persona`` is a 401 (the local adapter raises ``IdentityError``),
* with no persona header the default persona's subject becomes the audit actor, and
* a selected persona's subject becomes the audit actor.

The in-memory :class:`~model_quality_gate.config.Container` is injected by monkeypatching the
lru-cached ``deps.get_container`` (rather than mutating the environment) so the audit store
is inspectable and the run stays ephemeral.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from tests.conftest import LOOPBACK_PEER

from model_quality_gate.api import deps
from model_quality_gate.api.app import app
from model_quality_gate.config import Container, LocalSettings, Settings

_TARGET = {
    "model": "gemini-3.5-flash",
    "prompt_version": "v3",
    "dataset_id": "compliance-qa-golden",
}


def _local_settings_with_adapters() -> Settings:
    """Local Settings that carry the real port->adapter bindings from settings.yaml,
    with the local stores pointed at ephemeral in-memory SQLite."""
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


def _actors(container: Container) -> list[str]:
    return [event["actor"] for event in container.audit.read_all()]


def test_unknown_dev_persona_is_401(client: TestClient) -> None:
    resp = client.post(
        "/v1/evaluations",
        json={"target": _TARGET, "dataset_id": "compliance-qa-golden"},
        headers={"X-Dev-Persona": "does-not-exist"},
    )
    assert resp.status_code == 401


def test_default_persona_is_the_audit_actor(client: TestClient, container: Container) -> None:
    # No persona header: the local adapter resolves the default (first) persona, whose
    # subject must be the actor recorded in the audit trail (not a client-supplied value).
    resp = client.post(
        "/v1/evaluations",
        json={"target": _TARGET, "dataset_id": "compliance-qa-golden"},
    )
    assert resp.status_code == 200
    assert "demo.analyst@bank.example" in _actors(container)


def test_selected_persona_is_the_audit_actor(client: TestClient, container: Container) -> None:
    resp = client.post(
        "/v1/evaluations",
        json={"target": _TARGET, "dataset_id": "compliance-qa-golden"},
        headers={"X-Dev-Persona": "auditor"},
    )
    assert resp.status_code == 200
    assert "demo.auditor@bank.example" in _actors(container)


def test_client_supplied_actor_in_body_is_ignored(client: TestClient, container: Container) -> None:
    # A stray ``actor`` in the body must NOT become the audit actor: the schema drops it and
    # the verified persona subject wins.
    resp = client.post(
        "/v1/evaluations",
        json={
            "target": _TARGET,
            "dataset_id": "compliance-qa-golden",
            "actor": "attacker@evil.example",
        },
    )
    assert resp.status_code == 200
    actors = _actors(container)
    assert "attacker@evil.example" not in actors
    assert "demo.analyst@bank.example" in actors


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
