"""The profile has ONE source of truth, and it fails closed on an unset variable.

The standing gate for the absence-read-as-consent class, shared with Hrz7
(``human-review-console/tests/test_profile_single_source.py``).

The defect this guards: reading ``AI_QUALITY_PROFILE`` as a two-state value with ``local`` as
the default, in ``config/settings.yaml`` interpolation and again in ``Settings.load``.
``local`` is the profile THREE relaxations are granted to here, so a deployment whose
configuration never arrived gets all three at once: an unset ``AI_QUALITY_S2S_TOKEN`` leaves the
promotion gate open to any caller, the CORS allowlist falls back to localhost dev origins, and
HSTS is omitted. A drift guard is part of the rule, because any module that re-derives the
profile with its own permissive default can reintroduce the whole class in one line.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from tests.conftest import LOOPBACK_PEER

from model_quality_gate.api import deps
from model_quality_gate.api.app import app
from model_quality_gate.config import (
    RUNTIME_PROFILES,
    UNCONSENTED_PROFILE,
    Container,
    LocalSettings,
    ProfileError,
    Settings,
    resolve_profile,
)

_SRC = Path(__file__).resolve().parents[2] / "src" / "model_quality_gate"
_CONFIG = _SRC / "config.py"
_SETTINGS_YAML = _SRC.parents[1] / "config" / "settings.yaml"

_EVAL_BODY = {
    "target": {
        "model": "gemini-3.5-flash",
        "prompt_version": "v3",
        "dataset_id": "compliance-qa-golden",
    },
    "dataset_id": "compliance-qa-golden",
}


def _python_sources() -> list[Path]:
    return sorted(p for p in _SRC.rglob("*.py") if p != _CONFIG)


def test_only_the_resolver_reads_the_profile_variable_from_the_environment() -> None:
    offenders = []
    for path in _python_sources():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if re.search(r"(os\.environ|os\.getenv)[^\n]*PROFILE", line):
                offenders.append(f"{path.relative_to(_SRC)}:{number}: {line.strip()}")
    assert not offenders, (
        "these modules re-derive the profile instead of calling config.resolve_profile, "
        "so an unset AI_QUALITY_PROFILE can again be read as consent:\n" + "\n".join(offenders)
    )


def test_the_settings_file_declares_no_permissive_profile_default() -> None:
    """``${AI_QUALITY_PROFILE:-local}`` in the YAML is the same fail-open, one layer down."""
    match = re.search(
        r"^profile:\s*(\S+)", _SETTINGS_YAML.read_text(encoding="utf-8"), flags=re.MULTILINE
    )
    assert match is not None, "config/settings.yaml must still declare a profile key"
    assert match.group(1) == "${AI_QUALITY_PROFILE:-}", (
        "the settings file supplies a default for the profile, so an unset variable is "
        f"indistinguishable from a chosen one: {match.group(1)}"
    )


def test_the_resolver_treats_an_absent_variable_as_no_choice() -> None:
    choice = resolve_profile(environ={})
    assert choice.explicit is False
    assert choice.service_auth_configured is False


@pytest.mark.parametrize("blank", ["", "   "])
def test_the_resolver_refuses_a_configured_empty_profile(blank: str) -> None:
    with pytest.raises(ProfileError, match="AI_QUALITY_PROFILE"):
        resolve_profile(environ={"AI_QUALITY_PROFILE": blank})


def test_an_unconsented_run_is_not_the_local_profile_for_any_relaxation() -> None:
    choice = resolve_profile(environ={})
    assert choice.exposure_profile == UNCONSENTED_PROFILE
    assert choice.exposure_profile != "local"
    assert UNCONSENTED_PROFILE not in RUNTIME_PROFILES


def test_an_unconsented_run_still_binds_loopback() -> None:
    """The bind guard fails closed in the opposite direction: local is the restrictive case."""
    assert resolve_profile(environ={}).bind_profile == "local"


def test_a_deliberate_profile_is_carried_through_unchanged() -> None:
    choice = resolve_profile(environ={"AI_QUALITY_PROFILE": "gcp"})
    assert (choice.profile, choice.explicit) == ("gcp", True)
    assert choice.exposure_profile == "gcp"
    assert choice.bind_profile == "gcp"
    assert choice.service_auth_configured is True


def test_a_profile_named_only_in_the_settings_file_is_still_deliberate() -> None:
    choice = resolve_profile("platform", environ={})
    assert (choice.profile, choice.explicit) == ("platform", True)
    assert choice.exposure_profile == "platform"


@pytest.mark.parametrize("value", ["bogus", "Local", "GCP", "LOCAL", "local,gcp"])
def test_an_unknown_or_mis_capitalised_profile_refuses_to_load(value: str) -> None:
    with pytest.raises(ProfileError) as excinfo:
        resolve_profile(environ={"AI_QUALITY_PROFILE": value})
    assert "AI_QUALITY_PROFILE" in str(excinfo.value)


def test_surrounding_whitespace_is_stripped_rather_than_treated_as_a_typo() -> None:
    """A transport artifact is not a mis-capitalisation: strip, then match exactly."""
    assert resolve_profile(environ={"AI_QUALITY_PROFILE": " gcp "}).profile == "gcp"


# --------------------------------------------------------------------------- #
# The defect itself, end to end. The container is injected by monkeypatching the
# lru-cached ``deps.get_container`` (mirroring ``test_api_s2s_auth``), so the app reads
# unconsented settings without touching the process-wide container.
# --------------------------------------------------------------------------- #
def _settings(*, explicit: bool) -> Settings:
    base = Settings.load("config/settings.yaml")
    return Settings(
        project_id=base.project_id,
        region=base.region,
        profile="local",
        profile_explicit=explicit,
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
def unconsented_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    container = Container(_settings(explicit=False))
    monkeypatch.setattr(deps, "get_container", lambda: container)
    yield TestClient(app, client=LOOPBACK_PEER)


def test_an_unconsented_run_refuses_the_gate_routes_with_no_token_configured(
    unconsented_client: TestClient,
) -> None:
    """No profile chosen and no secret set must NOT let a caller drive the promotion gate."""
    assert unconsented_client.post("/v1/evaluations", json=_EVAL_BODY).status_code == 503
    # Liveness stays outside the guard, so an operator can still see the refusal.
    assert unconsented_client.get("/healthz").status_code == 200


def test_a_deliberate_local_run_keeps_the_zero_secret_opening_the_offline_gate_needs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = Container(_settings(explicit=True))
    monkeypatch.setattr(deps, "get_container", lambda: container)
    client = TestClient(app, client=LOOPBACK_PEER)
    assert client.post("/v1/evaluations", json=_EVAL_BODY).status_code == 200


def test_the_cors_dev_origin_fallback_is_withheld_from_an_unconsented_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The second relaxation: localhost dev origins belong to a chosen local, not to a gap.

    Trusting them without consent would let any local process on a user's machine call the
    promotion gate cross-origin with credentials. HSTS is the third relaxation and reads the
    same ``exposure_profile``; ``test_security_headers.py`` owns its assertions.
    """
    from model_quality_gate.api.app import _cors_origins

    monkeypatch.setattr(deps, "get_container", lambda: Container(_settings(explicit=True)))
    assert _cors_origins() == ["http://localhost:3000", "http://127.0.0.1:3000"]

    monkeypatch.setattr(deps, "get_container", lambda: Container(_settings(explicit=False)))
    assert _cors_origins() == []


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
