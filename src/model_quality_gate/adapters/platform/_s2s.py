"""Service-to-service (S2S) transport hardening shared by the platform adapters.

The ``platform`` profile's adapters are thin HTTP clients to the sibling
horizontal-platform services. Two controls apply to every call: base URLs must be
``https://`` outside loopback (caught at adapter construction), and when
``HRZ_S2S_TOKEN`` is set every request carries it as an ``Authorization: Bearer``
header; ``HRZ_S2S_SIGNING_KEY`` optionally propagates a verified end-user actor as an
HMAC-signed ``X-Aiq-Actor`` / ``X-Aiq-Actor-Sig`` pair.

**Sourced from the shared ``hex-service-kit`` commons.** This module
passes this repo's env-var and header names to :mod:`hex_service_kit.s2s`, so a fix to
the S2S transport rule is a version bump of the package rather than an N-repo edit.
"""

from __future__ import annotations

from hex_service_kit.netdefaults import read_env_setting
from hex_service_kit.s2s import client_headers, validate_base_url

#: Env var holding the bearer credential for S2S calls (empty = no header attached).
TOKEN_ENV = "HRZ_S2S_TOKEN"
#: Env var holding the HMAC key for signing the propagated end-user actor.
SIGNING_KEY_ENV = "HRZ_S2S_SIGNING_KEY"
_ACTOR_HEADER = "X-Aiq-Actor"
_ACTOR_SIG_HEADER = "X-Aiq-Actor-Sig"

__all__ = ["SIGNING_KEY_ENV", "TOKEN_ENV", "env_url", "headers", "validate_base_url"]


def env_url(name: str, default: str, *, service: str) -> str:
    """Resolve a service URL without letting SET-EMPTY inherit the localhost default."""
    setting = read_env_setting(name)
    if setting.is_configured_empty:
        raise ValueError(
            f"{name} is set but empty; unset it to use {default!r}, or provide a service URL"
        )
    return validate_base_url(setting.value or default, service=service)


def headers(*, settings: object, base_url: str, actor: str = "") -> dict[str, str]:
    """Auth headers for one S2S request (bearer token + optional signed actor)."""
    result = client_headers(
        actor,
        token_env=TOKEN_ENV,
        signing_key_env=SIGNING_KEY_ENV,
        actor_header=_ACTOR_HEADER,
        actor_sig_header=_ACTOR_SIG_HEADER,
    )
    managed = getattr(settings, "profile", "") in {"gcp", "platform"}
    if managed and base_url.startswith("https://") and "Authorization" not in result:
        result["Authorization"] = f"Bearer {_fetch_id_token(base_url)}"
    return result


def _fetch_id_token(audience: str) -> str:
    from google.auth.transport.requests import Request
    from google.oauth2.id_token import fetch_id_token

    return fetch_id_token(Request(), audience)
