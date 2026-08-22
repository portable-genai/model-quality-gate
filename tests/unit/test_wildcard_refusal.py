"""A wildcard in either origin policy refuses to boot, rather than being passed through.

Two allowlists decide who may talk to this service from a browser and who may frame its
console: ``AI_QUALITY_CORS_ORIGINS`` and ``AI_QUALITY_FRAME_ANCESTORS``. Both were resolved
carefully in three states and then handed on verbatim, so ``*`` travelled straight through to
``CORSMiddleware(allow_origins=["*"])`` and to ``Content-Security-Policy: frame-ancestors *``.
The prohibition existed only as a comment next to the variable ("never ``*``") and, for CORS,
as a sentence in the shared kit's own docstring. A comment is not a control.

A wildcard in either place is the whole origin policy switched off: any page on the internet
could frame the promotion-gate console and, with ``allow_credentials=True``, read
cross-origin responses. Both are resolved at module import, so refusing there makes this a
BOOT failure an operator sees immediately, not a surprise on some later request.

This file owns the one control across both variables. The three-state reads it sits on top of
are unchanged and asserted here too, because the wildcard case must not quietly alter what
unset or emptied means: ``tests/unit/test_security_headers.py`` and
``tests/unit/test_profile_single_source.py`` own the rest of those two stories.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from model_quality_gate.api.app import (
    _CORS_ORIGINS_ENV,
    _FRAME_ANCESTORS_ENV,
    _cors_origins,
    _frame_ancestors,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _boot(**overrides: str) -> subprocess.CompletedProcess[str]:
    """Import the API module in a fresh interpreter, the way uvicorn does at start-up."""
    env = dict(os.environ)
    env["AI_QUALITY_PROFILE"] = "local"
    env.pop(_CORS_ORIGINS_ENV, None)
    env.pop(_FRAME_ANCESTORS_ENV, None)
    env.update(overrides)
    env["PYTHONPATH"] = os.pathsep.join([str(REPO_ROOT / "src"), env.get("PYTHONPATH", "")])
    return subprocess.run(
        [sys.executable, "-c", "import model_quality_gate.api.app"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )


# --------------------------------------------------------------------------- #
# The refusal
# --------------------------------------------------------------------------- #
def test_a_wildcard_frame_ancestor_is_refused() -> None:
    with pytest.raises(ValueError, match="wildcard"):
        _frame_ancestors("*")


def test_a_wildcard_hidden_among_real_origins_is_refused() -> None:
    """The dangerous shape in practice: an allowlist that looks specific and is not."""
    with pytest.raises(ValueError, match="wildcard"):
        _frame_ancestors("https://portal.example *")


def test_a_wildcard_cors_origin_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_CORS_ORIGINS_ENV, "*")
    with pytest.raises(ValueError, match="wildcard"):
        _cors_origins()


def test_a_wildcard_among_real_cors_origins_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_CORS_ORIGINS_ENV, "https://portal.example,*")
    with pytest.raises(ValueError, match="wildcard"):
        _cors_origins()


@pytest.mark.parametrize("variable", [_FRAME_ANCESTORS_ENV, _CORS_ORIGINS_ENV])
def test_a_wildcard_refuses_at_boot_and_not_on_a_later_request(variable: str) -> None:
    """uvicorn imports this module at start-up, which is where an operator can still act."""
    result = _boot(**{variable: "*"})
    assert result.returncode != 0, f"{variable}=* must refuse to boot"
    assert variable in result.stderr
    assert "wildcard" in result.stderr


#: Every way an operator, a template or a YAML quirk can spell "everybody", checked against
#: both allowlists. ``ui/lib/csp.mjs`` refuses the same set on the document half.
_WILDCARD_SPELLINGS = ["*", "'*'", "null", "*.*", "https://*.example", "*.example", "https://*"]


@pytest.mark.parametrize("entry", _WILDCARD_SPELLINGS)
def test_every_wildcard_spelling_is_refused_in_either_list(
    monkeypatch: pytest.MonkeyPatch, entry: str
) -> None:
    """Measured before the fix: only the bare ``*`` was refused, and the other six were ACCEPTED.

    The check was ``"*" in origins``, a membership test over the SEQUENCE, so it saw an entry
    that IS an asterisk and not one that CONTAINS one. Nothing downstream inspected these
    values either: the resolved string goes straight into
    ``Content-Security-Policy: frame-ancestors`` and into ``CORSMiddleware(allow_origins=...)``,
    so there is no origin validator here to catch a spelling incidentally. All six reached a
    response header verbatim.

    Each one is a working wildcard. ``https://*.example`` is a CSP host-source wildcard, so
    every subdomain may frame the promotion-gate console including one an attacker takes over.
    ``'*'`` is what a quoted Terraform variable or a YAML string renders. ``*.*`` matches every
    name with a dot in it. ``null`` is the one that reads as harmless and is not: a SANDBOXED
    iframe presents the origin ``null``, so naming it hands framing and credentialed
    cross-origin rights to any page that can open one, and it carries no asterisk for a
    character test to find.
    """
    with pytest.raises(ValueError, match="wildcard"):
        _frame_ancestors(entry)

    monkeypatch.setenv(_CORS_ORIGINS_ENV, entry)
    with pytest.raises(ValueError, match="wildcard"):
        _cors_origins()


def test_the_refusal_still_admits_a_real_tenant_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    """A refusal that also turns away valid configuration is an outage, not a control.

    A port and a hyphen are the two shapes a hand-written token set gets wrong, and both are
    ordinary in a tenant origin: a hyphenated host is the norm and a non-443 port is how a
    staging portal is reached.
    """
    tenant = "https://portal.demo-bank.example:8443 https://admin-console.demo-bank.example"
    assert _frame_ancestors(tenant) == tenant

    monkeypatch.setenv(
        _CORS_ORIGINS_ENV,
        "https://portal.demo-bank.example:8443,https://admin-console.demo-bank.example",
    )
    assert _cors_origins() == [
        "https://portal.demo-bank.example:8443",
        "https://admin-console.demo-bank.example",
    ]


# --------------------------------------------------------------------------- #
# What must NOT change
# --------------------------------------------------------------------------- #
def test_a_legitimate_allowlist_still_boots(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _frame_ancestors("https://portal.example") == "https://portal.example"
    assert _frame_ancestors("https://portal.example https://admin.example") == (
        "https://portal.example https://admin.example"
    )
    monkeypatch.setenv(_CORS_ORIGINS_ENV, "https://portal.example,https://admin.example")
    assert _cors_origins() == ["https://portal.example", "https://admin.example"]

    result = _boot(**{_FRAME_ANCESTORS_ENV: "https://portal.example"})
    assert result.returncode == 0, result.stderr


def test_the_unset_and_emptied_states_are_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the wildcard case is new; the two states this repo already resolved must hold.

    Unset frame-ancestors keeps the shipped ``'self'`` and emptied still refuses for its own
    reason (an empty CSP directive is a parse error), which is a different refusal from this
    one and must not be swallowed by it. Unset CORS keeps the local dev fallback and emptied
    still denies every origin.
    """
    assert _frame_ancestors(None) == "'self'"
    with pytest.raises(ValueError, match=_FRAME_ANCESTORS_ENV):
        _frame_ancestors("")

    monkeypatch.delenv(_CORS_ORIGINS_ENV, raising=False)
    assert _cors_origins() == ["http://localhost:3000", "http://127.0.0.1:3000"]
    monkeypatch.setenv(_CORS_ORIGINS_ENV, "")
    assert _cors_origins() == []


def test_a_total_lockdown_is_still_expressible() -> None:
    """``'none'`` is the way to forbid all framing, and refusing ``*`` must not remove it."""
    assert _frame_ancestors("'none'") == "'none'"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
