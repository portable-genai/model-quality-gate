"""Identity value objects, re-exported from the commons rather than redeclared here.

``Principal``, ``RequestContext``, ``IdentityError`` and ``ANONYMOUS`` are NOT defined in this
module. They come from :mod:`hex_service_kit.identity`, where they are declared once for the whole
catalog. This repo had hand-copied them, and a value object copied into N repositories is N value
objects: only one of them gets fixed when a field or a rule changes. The copy here was already
identical field for field, which is precisely a shared type that had never been shared.

The semantics are unchanged. The service never trusts a client-asserted ``actor`` or ACL: a
:class:`Principal` is resolved server-side by an
:class:`~model_quality_gate.ports.identity.IdentityPort` adapter (local dev persona, GCP
IAP-verified assertion, or an on-prem client IdP) from the inbound transport context, and becomes
the audit actor recorded on every eval / red-team / gate event. The commons module is pure
standard library, so the domain stays framework-free and SDK-free exactly as before.
"""

from __future__ import annotations

from hex_service_kit.identity import ANONYMOUS as ANONYMOUS
from hex_service_kit.identity import IdentityError as IdentityError
from hex_service_kit.identity import Principal as Principal
from hex_service_kit.identity import RequestContext as RequestContext

__all__ = ["ANONYMOUS", "IdentityError", "Principal", "RequestContext"]
