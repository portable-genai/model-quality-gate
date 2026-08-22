"""Evaluation ports : the A4 core (scoring + adversarial red-team).

Primary GCP adapters: the **Gen AI evaluation service** on the Gemini Enterprise Agent
Platform (LLM-judge groundedness / faithfulness / safety, lazy ``vertexai ... .evals``)
for scoring, and a **Gemini-driven adversarial harness** for the red-team probes. On-prem
migration swaps these for placeholder adapters with no change to callers.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import (
    EvalDataset,
    EvalTarget,
    EvaluationOutcome,
    RedTeamCase,
    RedTeamReport,
)


@runtime_checkable
class EvaluationPort(Protocol):
    def score(
        self,
        target: EvalTarget,
        dataset: EvalDataset,
        metrics: list[str],
    ) -> dict[str, float] | EvaluationOutcome:
        """Return aggregate scores, optionally with redacted per-example evidence."""
        ...


@runtime_checkable
class RedTeamPort(Protocol):
    def run(self, target: EvalTarget, cases: list[RedTeamCase]) -> RedTeamReport:
        """Run the adversarial probes against ``target`` and return a RedTeamReport."""
        ...
