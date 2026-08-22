#!/usr/bin/env python3
"""Offline narrative-quality floor check for A4: is a reduced profile degraded, or unfit?

``eval/run_eval.py`` checks the gate LOGIC. This checks the other half, the one nothing in the
fleet measured: the quality of the NARRATIVE a model produces, scored against per-vertical floors
that a model-risk function owns as data (``config/quality-floors.toml``).

Why it lives here rather than in the service
--------------------------------------------
A4 is the promotion authority, and it is a MANAGED control. That is exactly why the gap existed:
the profile running the weaker local model was also the profile that cannot reach the authority,
so it had no quality measurement at all. This runs offline, in the ``local`` profile, with the
same deterministic judge a laptop or an on-prem install would use, so the reduced profile can
measure itself.

What a run does
---------------
Each golden case carries the same narrative written three ways, one per profile, the criteria a
good narrative for that case must satisfy, and the band each profile is EXPECTED to land in. The
judge grades every narrative and each score is compared to its vertical's floor and target:

    score >= target  ->  FIT       full quality
    floor <= score   ->  DEGRADED  usable, and visibly worse. This is the honest disclosure.
    score <  floor   ->  UNFIT     the profile must not serve this vertical

The run then checks the measured band against the recorded one, per case and per profile, which
makes ``expected`` in the golden set the DEGRADATION TABLE itself: a regression test on the
portability claim rather than a sentence in a blog post. A profile that quietly got worse fails
the run, and so does one that quietly got better, because both mean the published table is wrong.

Not falsely green
-----------------
Three structural rules, because a check on quality can lose the ability to say no without
anything looking different:

* the ``regressed`` control's expectation is forced to UNFIT at load, so it cannot be relabelled;
* at least one recorded expectation must be DEGRADED and at least one UNFIT, so the table cannot
  collapse into all-FIT, which would make the floor unfalsifiable; and
* a judge that grades no criteria is an error, never a score.

``tests/unit/test_narrative_floor.py`` adds the fourth: the judge itself is proven able to go red.

The judge
---------
Deterministic and offline by DEFAULT, so this runs with no model server, no network and no
credentials. ``--judge local-model`` opts in to a locally served OpenAI-compatible model (the
same server can serve the subject model and the judge), and it is never required by the gate.

The recorded bands are CALIBRATED AGAINST THE JUDGE, which is why every report names the judge
that produced it. Swapping judges moves the scores and is expected to: measured against a local
Gemma model rather than the offline judge, the managed narratives and the controls landed in the
same places (1.0 and 0.0), but the reduced narratives scored roughly 0.15 lower, which is enough
to move four of them from DEGRADED to UNFIT. So the run reports MISMATCH and fails, which is the
correct answer to "the bar moved", not a defect in either judge. Changing the default judge means
recalibrating the table, deliberately, in the same commit.

Usage::

    python eval/run_narrative_eval.py                       # offline, what CI runs
    python eval/run_narrative_eval.py --judge local-model \\
        --judge-base-url http://127.0.0.1:8001 --judge-model <model-id>

Exit code is ``0`` iff every measured band matches the recorded one and the structural rules hold.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from agent_eval_kit import EvalMetricResult, EvalReport
from agent_eval_kit.floors import (
    Fitness,
    FitnessVerdict,
    QualityFloorError,
    QualityFloors,
    load_quality_floors,
)
from agent_eval_kit.judge import (
    DETERMINISTIC_BACKEND,
    LOCAL_MODEL_BACKEND,
    JudgeConfigError,
    JudgePort,
    JudgeRequest,
    JudgeSelection,
    JudgeUnavailableError,
    NarrativeCriterion,
    build_judge,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATASET = _REPO_ROOT / "eval" / "datasets" / "narrative_golden.jsonl"
DEFAULT_FLOORS = _REPO_ROOT / "config" / "quality-floors.toml"

#: The profiles whose narratives are measured. ``managed`` is the managed-model profile,
#: ``reduced`` is the laptop / on-prem profile running a smaller local model.
MEASURED_PROFILES: tuple[str, ...] = ("managed", "reduced")
#: The control. Its narrative is written below the floor on purpose and its expectation is forced
#: to UNFIT, so a floor that has stopped refusing anything fails the run instead of passing it.
CONTROL_PROFILE = "regressed"
PROFILES: tuple[str, ...] = (*MEASURED_PROFILES, CONTROL_PROFILE)


@dataclass(frozen=True, slots=True)
class NarrativeCase:
    """One case: the criteria, each profile's narrative, and the band each is expected to hit."""

    id: str
    vertical: str
    criteria: tuple[NarrativeCriterion, ...]
    candidates: dict[str, str]
    expected: dict[str, Fitness]


@dataclass(frozen=True, slots=True)
class Measurement:
    """One narrative, measured: what the judge scored and how that compares to the record."""

    case: NarrativeCase
    profile: str
    verdict: FitnessVerdict

    @property
    def expected(self) -> Fitness:
        return self.case.expected[self.profile]

    @property
    def matches(self) -> bool:
        return self.verdict.fitness is self.expected

    def as_metric_result(self) -> EvalMetricResult:
        """The report row: did this narrative land in the band the table says it lands in?

        The score is the match, not the quality, because a DEGRADED row is a correct outcome
        rather than a failing one. The narrative's own score is printed in the table above it,
        where a reviewer reads the number instead of a pass mark.
        """
        return EvalMetricResult.scored(
            f"narrative_fitness[{self.case.id}/{self.profile}]",
            1.0 if self.matches else 0.0,
            1.0,
        )


def _fitness(value: object, *, where: str) -> Fitness:
    try:
        return Fitness(str(value))
    except ValueError as exc:
        allowed = ", ".join(item.value for item in Fitness)
        raise SystemExit(
            f"{where}: unknown expected band {value!r} (expected one of: {allowed})"
        ) from exc


def load_cases(path: Path) -> list[NarrativeCase]:
    """Parse the JSONL narrative golden set, failing closed on anything unmeasurable."""
    cases: list[NarrativeCase] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        where = f"{path}:{lineno}"
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{where}: invalid JSON: {exc}") from exc
        criteria_rows = obj.get("criteria") or []
        if not criteria_rows:
            raise SystemExit(f"{where}: a case with no criteria measures nothing")
        try:
            criteria = tuple(NarrativeCriterion.from_mapping(row) for row in criteria_rows)
        except JudgeConfigError as exc:
            raise SystemExit(f"{where}: {exc}") from exc
        candidates = {str(k): str(v) for k, v in (obj.get("candidates") or {}).items()}
        missing = [name for name in PROFILES if not candidates.get(name, "").strip()]
        if missing:
            raise SystemExit(
                f"{where}: no narrative for {', '.join(missing)}; every profile must be measured, "
                "and without the control nothing proves the floor can still refuse"
            )
        raw_expected = obj.get("expected") or {}
        if set(raw_expected) != set(PROFILES):
            raise SystemExit(
                f"{where}: 'expected' must record a band for exactly {', '.join(PROFILES)}"
            )
        expected = {name: _fitness(raw_expected[name], where=where) for name in PROFILES}
        if expected[CONTROL_PROFILE] is not Fitness.UNFIT:
            raise SystemExit(
                f"{where}: the {CONTROL_PROFILE} control must be expected UNFIT. Relabelling it "
                "would turn the one row that proves the floor still refuses into decoration"
            )
        vertical = str(obj.get("vertical", "")).strip()
        if not vertical:
            raise SystemExit(
                f"{where}: a case must name its vertical, or there is no floor to measure it "
                "against"
            )
        cases.append(
            NarrativeCase(
                id=str(obj.get("id", f"case-{lineno}")),
                vertical=vertical,
                criteria=criteria,
                candidates=candidates,
                expected=expected,
            )
        )
    if not cases:
        raise SystemExit(f"{path}: the narrative golden set is empty")
    return cases


def score_case(case: NarrativeCase, profile: str, judge: JudgePort) -> float:
    """Grade one case's narrative for one profile. Raises rather than defaulting a score."""
    verdict = judge.grade(
        JudgeRequest(
            candidate=case.candidates[profile],
            criteria=case.criteria,
            subject=f"{case.id}/{profile}",
        )
    )
    if not verdict.has_evidence:
        raise JudgeUnavailableError(
            f"{case.id}/{profile}: the judge graded no criteria, so there is no measurement"
        )
    return verdict.score


def measure(
    cases: list[NarrativeCase], judge: JudgePort, floors: QualityFloors
) -> list[Measurement]:
    """Grade every narrative and place each score in its vertical's band."""
    measurements: list[Measurement] = []
    for profile in PROFILES:
        for case in cases:
            score = score_case(case, profile, judge)
            measurements.append(
                Measurement(
                    case=case,
                    profile=profile,
                    verdict=floors.assess(case.vertical, score, profile=profile),
                )
            )
    return measurements


def build_report(dataset: Path, measurements: list[Measurement], n_cases: int) -> EvalReport:
    return EvalReport(
        dataset=str(dataset),
        results=tuple(item.as_metric_result() for item in measurements),
        n_examples=n_cases,
    )


def table_is_falsifiable(measurements: list[Measurement]) -> bool:
    """Does the recorded table still exercise both the degraded band and the refusal?

    A table where every row is expected FIT would pass forever with a floor of any value, which
    is the shape a quality bar decays into when nobody is watching.
    """
    recorded = {item.expected for item in measurements}
    return Fitness.DEGRADED in recorded and Fitness.UNFIT in recorded


def print_report(
    report: EvalReport,
    measurements: list[Measurement],
    *,
    judge_name: str,
    floors: QualityFloors,
) -> None:
    """Render the bands, not just a pass mark: a reviewer needs to see WHICH band, and why."""
    width = max(len(f"{item.case.id}/{item.profile}") for item in measurements)
    print("Narrative-quality floor report")
    print(f"  dataset : {report.dataset}")
    print(f"  floors  : {floors.source}")
    print(f"  judge   : {judge_name}")
    print(f"  cases   : {report.n_examples}\n")
    header = (
        f"  {'case/profile'.ljust(width)}   score   floor   target   measured   expected   result"
    )
    print(header)
    print("  " + "-" * (len(header) - 2))
    for item in measurements:
        label = f"{item.case.id}/{item.profile}".ljust(width)
        floor = item.verdict.floor
        print(
            f"  {label}   {item.verdict.score:5.3f}   {floor.floor:5.2f}   {floor.target:6.2f}   "
            f"{item.verdict.fitness.value.upper():<8}   {item.expected.value.upper():<8}   "
            f"{'OK' if item.matches else 'MISMATCH'}"
        )
    print()


def print_findings(measurements: list[Measurement]) -> None:
    """The prose a reviewer actually needs: which profile is unfit for which vertical, and why."""
    unfit = [
        item for item in measurements if item.profile in MEASURED_PROFILES and item.verdict.unfit
    ]
    degraded = [item for item in measurements if item.verdict.fitness is Fitness.DEGRADED]
    if degraded:
        print("  DEGRADED (usable, and visibly worse):")
        for item in degraded:
            print(f"    {item.case.vertical}/{item.profile}: {item.verdict.reason}")
    if unfit:
        print("  UNFIT (this profile must not serve this vertical):")
        for item in unfit:
            print(f"    {item.case.vertical}/{item.profile}: {item.verdict.reason}")
    mismatched = [item for item in measurements if not item.matches]
    if mismatched:
        print("  MISMATCHED against the recorded degradation table:")
        for item in mismatched:
            print(
                f"    {item.case.id}/{item.profile}: measured "
                f"{item.verdict.fitness.value}, the table records {item.expected.value}"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline narrative-quality floor check for A4.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--floors", type=Path, default=DEFAULT_FLOORS)
    parser.add_argument(
        "--judge",
        choices=(DETERMINISTIC_BACKEND, LOCAL_MODEL_BACKEND),
        default=DETERMINISTIC_BACKEND,
        help=(
            "deterministic (default): the offline judge, no server and no network. "
            "local-model: opt in to a locally served OpenAI-compatible judge."
        ),
    )
    parser.add_argument("--judge-base-url", default="")
    parser.add_argument("--judge-model", default="")
    args = parser.parse_args(argv)

    dataset: Path = args.dataset
    floors_path: Path = args.floors
    for path, label in ((dataset, "dataset"), (floors_path, "floors file")):
        if not path.exists():
            print(f"error: {label} not found: {path}", file=sys.stderr)
            return 2

    try:
        judge = build_judge(
            JudgeSelection(backend=args.judge, base_url=args.judge_base_url, model=args.judge_model)
        )
        floors = load_quality_floors(floors_path)
        cases = load_cases(dataset)
        measurements = measure(cases, judge, floors)
    except (JudgeConfigError, QualityFloorError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except JudgeUnavailableError as exc:
        print(f"error: the judge could not produce a verdict: {exc}", file=sys.stderr)
        return 2

    report = build_report(dataset, measurements, len(cases))
    print_report(report, measurements, judge_name=getattr(judge, "name", args.judge), floors=floors)
    print_findings(measurements)

    falsifiable = table_is_falsifiable(measurements)
    if not falsifiable:
        print(
            "  FLOOR CHECK: the recorded table no longer contains both a DEGRADED and an UNFIT "
            "row, so it would pass whatever the floors were set to"
        )
    passed = report.passed and falsifiable
    print(f"  NARRATIVE FLOOR: {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
