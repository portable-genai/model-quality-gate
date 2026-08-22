"""On-prem placeholder for ``EvaluationPort`` : the Google Distributed Cloud target.

One of the reversibility (P-02, P-12) migration placeholders: in the managed profile
this port binds to the Gen AI evaluation-service adapter; switching ``profile`` to
``onprem`` rebinds it here. The adapter constructs cleanly with **no external
dependencies** and structurally satisfies the same Protocol as the managed adapter, so
the contract tests prove interface parity. ``score`` deliberately raises rather than
returning vacuously-passing scores: an unimplemented evaluator must never wave a model
through unevaluated, so porting on-premise *must* supply a real eval backend. Filling
this body in is the only change required.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import EvalDataset, EvalTarget

_MESSAGE = (
    "On-prem EvaluationPort adapter is a migration placeholder; implement against your "
    "on-premise platform. Core domain logic is unchanged."
)


class OnPremEvalAdapter:
    """Placeholder evaluation adapter for the on-prem (Google Distributed Cloud) profile."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def score(
        self,
        target: EvalTarget,
        dataset: EvalDataset,
        metrics: list[str],
    ) -> dict[str, float]:
        raise NotImplementedError(_MESSAGE)
