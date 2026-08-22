"""FastAPI security: two orthogonal auth rings on every service-to-service route.

This module carries **two** independent checks that coexist on the mutating / promotion
surface, answering two different questions:

* :func:`get_principal` / :data:`CurrentPrincipal` : *who is the end USER?* Builds a
  :class:`RequestContext` from the inbound headers and asks the active profile's
  :class:`IdentityPort` adapter to resolve a verified :class:`Principal`. Any request-body
  ``actor`` is ignored: the audit actor flows from here, closing the spoofable-identity
  gap. This is the inner ring of the defense-in-depth PEP (edge IAP/Apigee -> Hrz1
  guardrail -> this per-backend check).
* :func:`require_service_caller` / :data:`ServiceCaller` : *which calling SERVICE is this?*
  Authenticates the peer service (e.g. a vertical's promotion-gate CI hitting ``/v1/gate``)
  from an ``Authorization: Bearer <token>`` credential, per the shared S2S contract. It does **not**
  replace the IAP identity: a request to a guarded route carries both an end-user identity
  and a service credential.

The S2S contract, by profile:

* exactly ``local``, deliberately chosen : a static shared secret from
  ``AI_QUALITY_S2S_TOKEN``, compared in constant time. When the env var is UNSET the API
  stays open (loopback dev only), so the offline test/eval gate runs with zero secrets; when
  SET, a request without the matching token is 401.
* ``gcp``/``platform`` (secure) : the bearer is a Google-signed OIDC ID token; its
  signature, issuer, expiry and audience (``AI_QUALITY_S2S_AUDIENCE``) are verified, then
  the caller service account is authorized against the ``AI_QUALITY_S2S_ALLOWED_CALLERS``
  allowlist (403 if unlisted). An unset audience or an empty allowlist is a 503, checked
  before the bearer is looked at, so an unconfigured identity policy cannot pass for a
  satisfied one. The google verification libs are imported lazily so the offline profile
  imports this module with no GCP SDK installed.
* anything else, INCLUDING an unconfigured deployment that never named a profile : the
  shared-secret path with no opening, so an unset ``AI_QUALITY_S2S_TOKEN`` is a 503.

That third case is why this module reads ``settings.exposure_profile`` rather than
``settings.profile``. The opening above belongs to a profile somebody deliberately chose;
before this, an absent ``AI_QUALITY_PROFILE`` resolved to ``local`` and therefore inherited
it, so a deployment that lost its configuration let any caller drive the promotion gate with
no credential at all. See :func:`model_quality_gate.config.resolve_profile`.

``/healthz``, ``/v1/personas`` and ``/.well-known/agent-card.json`` stay open (liveness,
the local persona picker, and public A2A discovery).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from hex_service_kit.web import make_require_service_caller

from ..domain.identity import IdentityError, Principal, RequestContext
from . import deps

_TOKEN_ENV = "AI_QUALITY_S2S_TOKEN"  # noqa: S105 - env var NAME, not a secret value
_ALLOWED_CALLERS_ENV = "AI_QUALITY_S2S_ALLOWED_CALLERS"
_AUDIENCE_ENV = "AI_QUALITY_S2S_AUDIENCE"


def get_principal(request: Request) -> Principal:
    """Resolve the verified end-user principal for this request, or raise 401."""
    ctx = RequestContext(headers={k.lower(): v for k, v in request.headers.items()})
    identity = deps.get_container().identity
    try:
        return identity.resolve(ctx)
    except IdentityError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
        ) from exc


# Reusable typed dependency for route signatures.
CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


# --------------------------------------------------------------------------- #
# Service-to-service (S2S) auth: authenticate the *calling service*, fail-closed.
# --------------------------------------------------------------------------- #
def _profile(request: Request) -> str:
    """The profile the S2S rule keys off: an unconsented run is NOT the ``local`` profile.

    Read through the same ``deps`` accessor the rest of the API uses.
    """
    return str(deps.get_settings().exposure_profile)


#: FastAPI dependency: authenticate the calling service by profile, fail-closed.
#: Coexists with :func:`get_principal`: this ring authenticates the peer SERVICE, the
#: Principal authenticates the end USER. Sourced from the shared hex-service-kit commons
#:: same env-var names and profile rule, behaviour unchanged.
require_service_caller = make_require_service_caller(
    _profile,
    token_env=_TOKEN_ENV,
    allowed_callers_env=_ALLOWED_CALLERS_ENV,
    audience_env=_AUDIENCE_ENV,
)

# Reusable dependency for route decorators (returns nothing; enforces or raises).
ServiceCaller = Depends(require_service_caller)
