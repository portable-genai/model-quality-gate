"""On-prem placeholder for ``MetricsStorePort`` : the Google Distributed Cloud target.

One of the reversibility (P-02, P-12) migration placeholders: in the managed profile
this port binds to the BigQuery metrics / drift store; switching ``profile`` to
``onprem`` rebinds it here. The adapter constructs cleanly with **no external
dependencies** and structurally satisfies the same Protocol as the managed adapter, so
the contract tests prove interface parity. Both methods raise rather than silently doing
nothing: a missing metrics store would hide model drift, a model-risk failure mode.
Filling these bodies in is the only change required.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import DriftSignal, EvalReport

_MESSAGE = (
    "On-prem MetricsStorePort adapter is a migration placeholder; implement against "
    "your on-premise platform. Core domain logic is unchanged."
)


class OnPremMetricsStoreAdapter:
    """Placeholder metrics / drift store adapter for the on-prem profile."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def record(self, report: EvalReport) -> None:
        raise NotImplementedError(_MESSAGE)

    def drift(self, model: str) -> list[DriftSignal]:
        raise NotImplementedError(_MESSAGE)
