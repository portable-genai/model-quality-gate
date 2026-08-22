"""On-prem placeholder for ``RedTeamPort`` : the Google Distributed Cloud target.

One of the reversibility (P-02, P-12) migration placeholders: in the managed profile
this port binds to the Gemini-driven adversarial harness; switching ``profile`` to
``onprem`` rebinds it here. The adapter constructs cleanly with **no external
dependencies** and structurally satisfies the same Protocol as the managed adapter, so
the contract tests prove interface parity. ``run`` deliberately raises rather than
returning a vacuously-passing report: an unimplemented red-team harness must never
declare a model safe without probing it. Filling this body in is the only change required.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import EvalTarget, RedTeamCase, RedTeamReport

_MESSAGE = (
    "On-prem RedTeamPort adapter is a migration placeholder; implement against your "
    "on-premise platform. Core domain logic is unchanged."
)


class OnPremRedTeamAdapter:
    """Placeholder red-team adapter for the on-prem (Google Distributed Cloud) profile."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def run(self, target: EvalTarget, cases: list[RedTeamCase]) -> RedTeamReport:
        raise NotImplementedError(_MESSAGE)
