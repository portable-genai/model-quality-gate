"""Security-header baseline on every surface (practice C6).

Two surfaces, two enforcement points:

* the API, whose middleware is the shared ``hex_service_kit.web.add_security_headers``
  (adopted, not copied) : CSP frame-ancestors, nosniff, Referrer-Policy, and HSTS on any
  non-local profile;
* the Next.js console, whose own config must emit a full default-deny CSP with a scoped
  ``connect-src``, because the document a browser frames is served by Next.js and never
  passes through the API middleware.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hex_service_kit.web import add_security_headers
from tests.conftest import LOOPBACK_PEER

from model_quality_gate.api.app import _FRAME_ANCESTORS_ENV, _frame_ancestors, app

REPO_ROOT = Path(__file__).resolve().parents[2]
NEXT_CONFIG = REPO_ROOT / "ui" / "next.config.mjs"
# The policy itself moved out of the static `headers()` table and into its own module: it
# carries a per-request script nonce, and a static header table cannot express one.
UI_CSP = REPO_ROOT / "ui" / "lib" / "csp.mjs"
UI_PROXY = REPO_ROOT / "ui" / "proxy.ts"


# --------------------------------------------------------------------------- #
# API surface
# --------------------------------------------------------------------------- #
def test_api_emits_the_full_header_baseline() -> None:
    response = TestClient(app, client=LOOPBACK_PEER).get("/healthz")
    assert response.status_code == 200
    headers = response.headers
    assert headers["content-security-policy"] == "frame-ancestors 'self'"
    assert headers["x-frame-options"] == "SAMEORIGIN"
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["referrer-policy"] == "no-referrer"


def test_api_omits_hsts_on_the_local_profile() -> None:
    """The local profile is plain-HTTP loopback; pinning it to https breaks the demo."""
    response = TestClient(app, client=LOOPBACK_PEER).get("/healthz")
    assert "strict-transport-security" not in response.headers


def test_api_sends_hsts_on_a_secure_profile() -> None:
    """Every non-local profile terminates TLS in front of the service, so HSTS applies."""
    secure = FastAPI()

    @secure.get("/healthz")
    def _healthz() -> dict[str, str]:
        return {"status": "ok"}

    add_security_headers(secure, frame_ancestors="'self'", profile="gcp")
    headers = TestClient(secure, client=LOOPBACK_PEER).get("/healthz").headers
    assert headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["referrer-policy"] == "no-referrer"


# --------------------------------------------------------------------------- #
# Three-state AI_QUALITY_FRAME_ANCESTORS
# --------------------------------------------------------------------------- #
def test_frame_ancestors_resolves_three_states_not_two() -> None:
    """Unset keeps the default; a set-and-empty value is never resolved to that default."""
    assert _frame_ancestors(None) == "'self'"
    assert _frame_ancestors("https://portal.example") == "https://portal.example"
    assert _frame_ancestors(" https://portal.example  https://admin.example ") == (
        "https://portal.example https://admin.example"
    )
    with pytest.raises(ValueError, match=_FRAME_ANCESTORS_ENV):
        _frame_ancestors("")
    with pytest.raises(ValueError, match=_FRAME_ANCESTORS_ENV):
        _frame_ancestors("   ")


def test_an_emptied_frame_ancestors_refuses_to_boot_rather_than_dropping_the_control() -> None:
    """The whole point: an empty directive is a CSP parse error browsers throw away.

    Before this was three-state the service booted happily and answered every request with
    ``Content-Security-Policy: frame-ancestors `` and no ``X-Frame-Options``, so the
    clickjacking restriction was gone from both channels with nothing in the response saying
    so. Boot now fails instead, because uvicorn imports this module at start-up.
    """
    env = dict(os.environ)
    env[_FRAME_ANCESTORS_ENV] = ""
    env["AI_QUALITY_PROFILE"] = "local"
    env["PYTHONPATH"] = os.pathsep.join([str(REPO_ROOT / "src"), env.get("PYTHONPATH", "")])
    result = subprocess.run(
        [sys.executable, "-c", "import model_quality_gate.api.app"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0, "an emptied frame-ancestors allowlist must refuse to boot"
    assert _FRAME_ANCESTORS_ENV in result.stderr
    assert "'none'" in result.stderr, "the refusal must name the way to express a lockdown"


def test_a_total_lockdown_stays_expressible() -> None:
    """Refusing on empty must not remove the operator's ability to forbid all framing."""
    locked = FastAPI()

    @locked.get("/healthz")
    def _healthz() -> dict[str, str]:
        return {"status": "ok"}

    add_security_headers(locked, frame_ancestors=_frame_ancestors("'none'"), profile="gcp")
    headers = TestClient(locked, client=LOOPBACK_PEER).get("/healthz").headers
    assert headers["content-security-policy"] == "frame-ancestors 'none'"


# --------------------------------------------------------------------------- #
# UI surface
# --------------------------------------------------------------------------- #
def test_ui_config_emits_a_full_default_deny_csp() -> None:
    config = UI_CSP.read_text()
    for directive in (
        "default-src 'self'",
        "base-uri 'self'",
        "form-action 'self'",
        "object-src 'none'",
        "script-src 'self'",
        "connect-src",
        "frame-ancestors",
    ):
        assert directive in config, f"missing CSP directive: {directive}"


def test_ui_connect_src_is_scoped_to_self_plus_the_api_origin() -> None:
    """No wildcard: the console talks to its own origin and the A4 API origin only."""
    policy = UI_CSP.read_text()
    assert 'const connectSrc = ["\'self\'", apiOrigin(env)].filter(Boolean).join(" ")' in policy
    api_base = (REPO_ROOT / "ui" / "lib" / "api-base.mjs").read_text()
    assert "new URL(base).origin" in api_base  # only the origin enters the CSP
    assert "connect-src *" not in policy


def test_ui_sets_nosniff_referrer_policy_and_hsts() -> None:
    config = NEXT_CONFIG.read_text()
    assert re.search(r'key:\s*"X-Content-Type-Options",\s*value:\s*"nosniff"', config)
    assert re.search(r'key:\s*"Referrer-Policy",\s*value:\s*"no-referrer"', config)
    assert "Strict-Transport-Security" in config
    assert "max-age=31536000; includeSubDomains" in config


def test_ui_csp_allowlists_no_external_host() -> None:
    """A CDN host in the policy would undo the point of a default-deny CSP."""
    policy = UI_CSP.read_text()
    policy_block = policy[policy.index("export function contentSecurityPolicy") :]
    assert "http://" not in policy_block
    assert "https://" not in policy_block


def test_ui_script_src_is_nonced_and_the_route_is_dynamic() -> None:
    """The console served dead markup until these two agreed, and both are needed.

    `script-src 'self'` blocked Next's inline hydration bootstrap, so React never attached and
    the six controls did nothing while every header, type-check and test stayed green. The nonce
    fixes that only if the route is dynamically rendered: a prerendered page was built before the
    nonce existed, and `'strict-dynamic'` then blocks the chunk scripts that plain `'self'` had
    been loading, which is strictly worse.
    """
    policy = UI_CSP.read_text()
    assert "'nonce-${nonce}' 'strict-dynamic'" in policy
    assert "'unsafe-inline'" not in policy.split("const scriptSrc")[1].split("\n")[0]
    # The nonce reaches Next only through the REQUEST header, under this exact name.
    proxy = UI_PROXY.read_text()
    assert 'requestHeaders.set("Content-Security-Policy", csp)' in proxy
    # And the build refuses the half-configured combination outright.
    assert "assertHydratableCsp" in NEXT_CONFIG.read_text()
    assert (
        'export const dynamic = "force-dynamic"'
        in (REPO_ROOT / "ui" / "app" / "layout.tsx").read_text()
    )
