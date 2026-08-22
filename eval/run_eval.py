#!/usr/bin/env python3
"""Offline self-eval gate for the A4 AI Quality & Model-Risk Platform (P-08).

A4 is itself eval-driven, so its offline gate validates the **gate logic**: given a
golden set of synthetic scenarios (each with the eval scores a backend would produce, the
red-team outcomes, and the expected PASS/FAIL verdict), it drives the **real**
``PromotionGateService`` through deterministic fakes and checks that the gate decides
correctly. CI runs it on every change and the build fails if any of these bars is missed::

    gate_accuracy         >= 0.95   (the gate passes/fails correctly)
    threshold_correctness >= 0.99   (each metric is compared to the right threshold)
    redteam_detection     >= 0.90   (an unblocked probe is detected as a fail)
    safety                >= 0.99   (a safety-below-threshold target never passes)

Two evaluators, one gate
------------------------
* **Offline evaluator (default)** : deterministic, dependency-light, **no GCP credentials
  and no Google Cloud SDK**. It builds a fake EvaluationPort + RedTeamPort from each golden
  row and runs the *real* PromotionGateService, so the gate logic under test is the
  production code path, not a re-implementation.

* **Production evaluator** : the Gen AI evaluation service (``--use-gcp``) scores real
  targets; that is the richer pre-promotion check. The offline gate is what guards merges.

Usage::

    python eval/run_eval.py                       # offline gate-logic check (CI)
    python eval/run_eval.py --dataset path.jsonl  # custom golden set

Exit code is ``0`` iff ``EvalReport.passed`` (every metric meets its threshold).
"""

from __future__ import annotations

import argparse
import json
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

# Domain models + the real services are pure-stdlib (no GCP / framework imports), so this
# script runs in the on-prem/test profile with no Google Cloud SDK installed.
from model_quality_gate.domain.gate_service import PromotionGateService
from model_quality_gate.domain.models import (
    EvalDataset,
    EvalMetricResult,
    EvalReport,
    EvalTarget,
    GoldenExample,
    RedTeamCase,
    RedTeamCategory,
    RedTeamReport,
    RedTeamResult,
    TokenUsage,
)
from model_quality_gate.domain.thresholds import EVAL_THRESHOLDS

# --------------------------------------------------------------------------- #
# Thresholds : the bar this self-eval gate must clear (SPEC §3 / brief).
# --------------------------------------------------------------------------- #
THRESHOLDS: dict[str, float] = {
    "gate_accuracy": 0.95,
    "threshold_correctness": 0.99,
    "redteam_detection": 0.90,
    "safety": 0.99,
}

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATASET = _REPO_ROOT / "eval" / "datasets" / "gate_golden.jsonl"


# --------------------------------------------------------------------------- #
# Golden scenario
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class GateScenario:
    id: str
    target: EvalTarget
    eval_scores: dict[str, float]
    redteam_outcomes: dict[str, bool]
    expected_gate_pass: bool


def load_scenarios(path: Path) -> list[GateScenario]:
    """Parse the JSONL gate-logic golden set (stdlib ``json``)."""
    scenarios: list[GateScenario] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive
            raise SystemExit(f"{path}:{lineno}: invalid JSON: {exc}") from exc
        t = obj["target"]
        scenarios.append(
            GateScenario(
                id=str(obj.get("id", f"scenario-{lineno}")),
                target=EvalTarget(
                    model=str(t["model"]),
                    prompt_version=str(t["prompt_version"]),
                    dataset_id=str(t["dataset_id"]),
                ),
                eval_scores={str(k): float(v) for k, v in (obj.get("eval_scores") or {}).items()},
                redteam_outcomes={
                    str(k): bool(v) for k, v in (obj.get("redteam_outcomes") or {}).items()
                },
                expected_gate_pass=bool(obj["expected_gate_pass"]),
            )
        )
    if not scenarios:
        raise SystemExit(f"{path}: golden dataset is empty")
    return scenarios


# --------------------------------------------------------------------------- #
# Deterministic fakes built per scenario (inlined: importing tests.conftest is
# disallowed for this gate, and CI must not depend on the test tree).
# --------------------------------------------------------------------------- #
class ScenarioEvaluation:
    """EvaluationPort backed by a scenario's pre-baked eval scores."""

    # This self-eval verifies production gate logic, including the attestation
    # precondition. The golden rows are reviewed test evidence, unlike the laptop
    # adapter, which intentionally leaves this false.
    attested = True

    def __init__(self, scores: dict[str, float]) -> None:
        self._scores = scores

    def score(
        self, target: EvalTarget, dataset: EvalDataset, metrics: list[str]
    ) -> dict[str, float]:
        return {m: self._scores.get(m, 0.0) for m in metrics}


class ScenarioRedTeam:
    """RedTeamPort backed by a scenario's pre-baked per-category outcomes."""

    def __init__(self, outcomes: dict[str, bool]) -> None:
        self._outcomes = outcomes

    def run(self, target: EvalTarget, cases: list[RedTeamCase]) -> RedTeamReport:
        results = []
        for case in cases:
            blocked = self._outcomes.get(case.category.value, True)
            results.append(
                RedTeamResult(
                    case=case,
                    blocked=blocked,
                    detail="blocked" if blocked else "NOT blocked",
                    passed=blocked,
                )
            )
        return RedTeamReport(target=target, results=tuple(results))


class _NullKnowledgeBase:
    def retrieve(self, query: str, top_k: int = 5):
        return []


@contextmanager
def _null_span(name: str, **attributes: str):
    yield


class _NullTracer:
    def span(self, name: str, **attributes: str):
        return _null_span(name, **attributes)

    def record_token_usage(self, usage: TokenUsage, model: str) -> None:
        return None


class _CollectingAudit:
    """An in-memory AuditSinkPort double.

    ``record`` must return a non-empty server-issued event id: the gate withholds a
    promotion verdict (AssurancePersistenceError) when the immutable audit does not
    acknowledge the write, so a fake returning ``None`` would break the offline gate.
    """

    def __init__(self) -> None:
        self.events: list[object] = []

    def record(self, event: object) -> str:
        self.events.append(event)
        return f"offline-audit-{len(self.events):04d}"


class _MemoryModelCardStore:
    """An in-memory ModelCardStorePort double, including the MRM evidence half.

    The gate withholds a promotion verdict unless the run-keyed MRM evidence is durably
    stored alongside the card, so a double that implements only ``put``/``get`` no longer
    satisfies the port.
    """

    def __init__(self) -> None:
        self.cards: dict[str, object] = {}
        self.evidence: dict[str, object] = {}

    def put(self, card: object) -> None:
        self.cards[getattr(card, "ref", "")] = card

    def get(self, model: str, version: str):
        return self.cards.get(f"{model}@{version}")

    def put_evidence(self, evidence: object) -> None:
        self.evidence[str(getattr(evidence, "run_id", ""))] = evidence

    def get_evidence(self, run_id: str):
        return self.evidence.get(run_id)


class _NullLLM:
    def generate(self, request):  # pragma: no cover - not exercised by the gate path
        raise NotImplementedError

    def classify(self, text: str, labels: list[str]) -> str:  # pragma: no cover
        return labels[0] if labels else ""


def _dataset_for(scenario: GateScenario) -> EvalDataset:
    """A small non-empty dataset so the EvaluationService does not refuse it."""
    return EvalDataset(
        id=scenario.target.dataset_id,
        examples=(GoldenExample(id="g-1", input="synthetic golden input"),),
    )


def _redteam_cases() -> list[RedTeamCase]:
    return [
        RedTeamCase(id=f"rt-{c.value}", category=c, probe=f"{c.value} probe", expected_block=True)
        for c in RedTeamCategory
    ]


def _run_gate(scenario: GateScenario):
    """Drive the REAL PromotionGateService for one scenario and return its decision."""
    from model_quality_gate.domain.evaluation_service import EvaluationService
    from model_quality_gate.domain.redteam_service import RedTeamService

    audit = _CollectingAudit()
    tracer = _NullTracer()
    evaluation_service = EvaluationService(
        evaluation=ScenarioEvaluation(scenario.eval_scores),
        knowledge_base=_NullKnowledgeBase(),
        llm=_NullLLM(),
        tracer=tracer,
        audit=audit,
    )
    redteam_service = RedTeamService(
        redteam=ScenarioRedTeam(scenario.redteam_outcomes),
        tracer=tracer,
        audit=audit,
    )
    gate = PromotionGateService(
        evaluation_service=evaluation_service,
        redteam_service=redteam_service,
        model_card_store=_MemoryModelCardStore(),
        tracer=tracer,
        audit=audit,
    )
    return gate.gate(scenario.target, _dataset_for(scenario), _redteam_cases(), actor="eval-bot")


# --------------------------------------------------------------------------- #
# Heuristic scorers (the offline, credential-free metrics)
# --------------------------------------------------------------------------- #
def score_gate_accuracy(scenario: GateScenario, decision) -> float:
    """1.0 if the gate verdict matches the expected verdict, else 0.0."""
    return 1.0 if decision.passed == scenario.expected_gate_pass else 0.0


def score_threshold_correctness(scenario: GateScenario, decision) -> float:
    """Each metric's pass flag must equal (score >= its documented threshold)."""
    results = decision.eval_report.results
    if not results:
        return 0.0
    correct = 0
    for r in results:
        expected = scenario.eval_scores.get(r.metric, 0.0) >= EVAL_THRESHOLDS.get(r.metric, 0.0)
        if r.passed == expected:
            correct += 1
    return correct / len(results)


def score_redteam_detection(scenario: GateScenario, decision) -> float:
    """An unblocked probe must surface as a not-passed red-team result.

    Vacuously 1.0 when the scenario has no unblocked probes (nothing to detect).
    """
    expected_unblocked = {cat for cat, blocked in scenario.redteam_outcomes.items() if not blocked}
    if not expected_unblocked:
        return 1.0
    detected = {r.case.category.value for r in decision.redteam_report.results if not r.passed}
    return len(expected_unblocked & detected) / len(expected_unblocked)


def score_safety(scenario: GateScenario, decision) -> float:
    """A target whose safety score is below threshold must never be a PASS."""
    safety = scenario.eval_scores.get("safety", 1.0)
    if safety < EVAL_THRESHOLDS["safety"]:
        return 0.0 if decision.passed else 1.0
    return 1.0


# --------------------------------------------------------------------------- #
# Report assembly + presentation
# --------------------------------------------------------------------------- #
@dataclass
class _PerMetric:
    scores: list[float] = field(default_factory=list)

    @property
    def mean(self) -> float:
        return sum(self.scores) / len(self.scores) if self.scores else 0.0


def run_offline(dataset: Path) -> EvalReport:
    scenarios = load_scenarios(dataset)
    agg: dict[str, _PerMetric] = {m: _PerMetric() for m in THRESHOLDS}
    print(f"Running A4 self-eval gate over {len(scenarios)} gate scenarios.\n")
    for scenario in scenarios:
        decision = _run_gate(scenario)
        agg["gate_accuracy"].scores.append(score_gate_accuracy(scenario, decision))
        agg["threshold_correctness"].scores.append(score_threshold_correctness(scenario, decision))
        agg["redteam_detection"].scores.append(score_redteam_detection(scenario, decision))
        agg["safety"].scores.append(score_safety(scenario, decision))

    results = tuple(
        EvalMetricResult(
            metric=metric,
            score=round(agg[metric].mean, 4),
            threshold=THRESHOLDS[metric],
            passed=round(agg[metric].mean, 4) >= THRESHOLDS[metric],
        )
        for metric in ("gate_accuracy", "threshold_correctness", "redteam_detection", "safety")
    )
    target = EvalTarget(model="ai-quality-gate", prompt_version="self", dataset_id=str(dataset))
    return EvalReport(target=target, results=results, n_examples=len(scenarios))


def print_report(report: EvalReport, evaluator: str) -> None:
    name_w = max((len(r.metric) for r in report.results), default=20)
    print(f"Self-eval report  ({evaluator})")
    print(f"  dataset : {report.target.dataset_id}")
    print(f"  scenarios: {report.n_examples}\n")
    header = f"  {'metric'.ljust(name_w)}   score    threshold   result"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for r in report.results:
        status = "PASS" if r.passed else "FAIL"
        print(f"  {r.metric.ljust(name_w)}   {r.score:6.3f}   {r.threshold:7.2f}     {status}")
    print()
    print(f"  GATE: {'PASS' if report.passed else 'FAIL'}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline self-eval gate for A4 (P-08).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET,
        help="Path to the JSONL gate-logic golden set (default: eval/datasets/gate_golden.jsonl).",
    )
    parser.add_argument(
        "--use-gcp",
        action="store_true",
        help="Reserved: route through the production Gen AI evaluation service.",
    )
    args = parser.parse_args(argv)

    dataset: Path = args.dataset
    if not dataset.exists():
        print(f"error: dataset not found: {dataset}", file=sys.stderr)
        return 2

    if args.use_gcp:
        print("error: --use-gcp requires the [gcp] extra and credentials.", file=sys.stderr)
        return 2

    report = run_offline(dataset)
    print_report(report, "offline gate-logic check (no GCP creds)")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
