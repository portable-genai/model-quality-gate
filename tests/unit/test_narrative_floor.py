"""The narrative-quality floor, and the not-falsely-green proof turned on the JUDGE itself.

A4 is the promotion authority, so the quality bar it applies to everyone else has to be one it
can prove still works. The gate-logic proofs live in `tests/test_not_falsely_green.py`; these are
the narrative half, and they are almost all falsification:

* the judge can go red, PER VERTICAL, against a narrative carrying that vertical's own defect;
* a judge that certifies anything is caught rather than trusted;
* an absent measurement is UNFIT, never a pass;
* an unnamed vertical raises instead of inheriting somebody else's bar; and
* the recorded degradation table cannot be relabelled into one that always passes.

Nothing here needs a model server. The offline judge is the default, and one test proves a stray
environment variable cannot redirect the gate to a network judge.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest
from agent_eval_kit.floors import Fitness, MissingFloorError, load_quality_floors
from agent_eval_kit.harness import NotFalselyGreenError
from agent_eval_kit.judge import (
    JUDGE_BACKEND_ENV,
    JUDGE_BASE_URL_ENV,
    JUDGE_MODEL_ENV,
    CriterionScore,
    DeterministicNarrativeJudge,
    JudgeRequest,
    JudgeSelection,
    JudgeUnavailableError,
    JudgeVerdict,
    assert_judge_can_go_red,
    build_judge,
)
from agent_eval_kit.report import EvalReport
from eval.run_narrative_eval import (
    CONTROL_PROFILE,
    DEFAULT_DATASET,
    DEFAULT_FLOORS,
    MEASURED_PROFILES,
    Measurement,
    build_report,
    load_cases,
    main,
    measure,
    score_case,
    table_is_falsifiable,
)

from model_quality_gate.domain.thresholds import METRIC_BUNDLES

_CASES = load_cases(DEFAULT_DATASET)
_FLOORS = load_quality_floors(DEFAULT_FLOORS)
_JUDGE = DeterministicNarrativeJudge()


class _AlwaysHappyJudge:
    """A judge that certifies anything. The failure mode a quality bar cannot see from inside."""

    name = "always-happy/v0"

    def grade(self, request: JudgeRequest) -> JudgeVerdict:
        return JudgeVerdict(
            graded_by=self.name,
            scores=tuple(
                CriterionScore(criterion=item.name, score=1.0, weight=item.weight)
                for item in request.criteria
            ),
        )


class _SilentJudge:
    """A judge that returns a verdict with nothing in it."""

    name = "silent/v0"

    def grade(self, request: JudgeRequest) -> JudgeVerdict:
        return JudgeVerdict(graded_by=self.name, scores=())


# --------------------------------------------------------------------------- #
# The floor is data, and every floor is measured
# --------------------------------------------------------------------------- #
def test_the_floors_file_loads_and_names_real_verticals() -> None:
    """A floor for a vertical this service has no bundle for would be a number about nothing."""
    assert _FLOORS.verticals
    unknown = [name for name in _FLOORS.verticals if name not in METRIC_BUNDLES]
    assert not unknown, f"quality-floors.toml names verticals with no metric bundle: {unknown}"


def test_every_floor_is_measured_and_every_case_has_a_floor() -> None:
    """A floor with no narrative behind it is decoration, and the reverse is an unmeasured case."""
    measured = {case.vertical for case in _CASES}
    assert measured == set(_FLOORS.verticals), (
        f"the golden set measures {sorted(measured)} but the floors file names "
        f"{sorted(_FLOORS.verticals)}; one of them is drifting"
    )


def test_a_vertical_with_no_floor_raises_rather_than_borrowing_one() -> None:
    with pytest.raises(MissingFloorError):
        _FLOORS.floor_for("doc9-not-a-real-vertical")


# --------------------------------------------------------------------------- #
# The judge itself can go red, per vertical
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("case", _CASES, ids=lambda case: case.id)
def test_the_judge_can_go_red_for_each_case(case) -> None:  # type: ignore[no-untyped-def]
    """Per case, not once overall: each vertical carries its own floor and its own defect.

    Green is the managed narrative, red is the control written below that vertical's floor. If
    this passes for every case, the judge can still tell them apart at the bar that matters.
    """
    assert_judge_can_go_red(
        _JUDGE,
        criteria=case.criteria,
        green=case.candidates["managed"],
        red=case.candidates[CONTROL_PROFILE],
        floor=_FLOORS.floor_for(case.vertical).floor,
        metric=f"narrative_quality[{case.vertical}]",
    )


def test_a_judge_that_certifies_anything_is_caught() -> None:
    """The control on the control. Without it, a judge stuck at 1.0 looks like a strict one."""
    case = _CASES[0]
    with pytest.raises(NotFalselyGreenError, match="FALSELY GREEN"):
        assert_judge_can_go_red(
            _AlwaysHappyJudge(),
            criteria=case.criteria,
            green=case.candidates["managed"],
            red=case.candidates[CONTROL_PROFILE],
            floor=_FLOORS.floor_for(case.vertical).floor,
        )


def test_a_judge_that_grades_nothing_is_an_error_not_a_score() -> None:
    with pytest.raises(JudgeUnavailableError, match="graded no criteria"):
        score_case(_CASES[0], "managed", _SilentJudge())


def test_an_absent_measurement_is_unfit_rather_than_a_pass() -> None:
    """The `EvalReport(metrics=[]).passed is True` class, at the floor rather than in the report."""
    verdict = _FLOORS.assess_verdict(
        _CASES[0].vertical, JudgeVerdict(graded_by="silent/v0", scores=()), profile="reduced"
    )
    assert verdict.fitness is Fitness.UNFIT
    assert verdict.score == 0.0


def test_an_empty_report_cannot_read_as_a_pass() -> None:
    """A run that measured nothing must not be indistinguishable from a run that measured well."""
    assert build_report(DEFAULT_DATASET, [], len(_CASES)).passed is False
    assert EvalReport(dataset="d", results=(), n_examples=len(_CASES)).passed is False


# --------------------------------------------------------------------------- #
# The recorded degradation table
# --------------------------------------------------------------------------- #
def test_the_measured_bands_match_the_recorded_table() -> None:
    measurements = measure(_CASES, _JUDGE, _FLOORS)
    mismatched = [item for item in measurements if not item.matches]
    assert not mismatched, [
        f"{item.case.id}/{item.profile}: measured {item.verdict.fitness.value}, "
        f"recorded {item.expected.value}"
        for item in mismatched
    ]


def test_the_table_records_a_degraded_row_and_a_refusal() -> None:
    """Otherwise the check would pass whatever the floors were set to."""
    assert table_is_falsifiable(measure(_CASES, _JUDGE, _FLOORS)) is True


def test_an_all_fit_table_is_reported_as_unfalsifiable() -> None:
    measurements = measure(_CASES, _JUDGE, _FLOORS)
    all_fit = [
        Measurement(
            case=item.case.__class__(
                id=item.case.id,
                vertical=item.case.vertical,
                criteria=item.case.criteria,
                candidates=item.case.candidates,
                expected=dict.fromkeys(item.case.expected, Fitness.FIT),
            ),
            profile=item.profile,
            verdict=item.verdict,
        )
        for item in measurements
    ]
    assert table_is_falsifiable(all_fit) is False


def test_the_reduced_profile_is_unfit_somewhere_and_degraded_somewhere() -> None:
    """The finding this whole check exists to state, asserted rather than described.

    The reduced profile is not uniformly "a bit worse": it is usable for some verticals and
    unusable for the strictest one. That distinction is the difference between a floor and a
    disclaimer, and it is what a buyer needs before choosing the off-cloud profile.
    """
    reduced = [item for item in measure(_CASES, _JUDGE, _FLOORS) if item.profile == "reduced"]
    bands = {item.verdict.fitness for item in reduced}
    assert Fitness.DEGRADED in bands and Fitness.UNFIT in bands, bands


def test_the_control_expectation_cannot_be_relabelled(tmp_path: Path) -> None:
    """Relabelling the control is the cheapest way to make this check green with no floor left."""
    row = json.loads(
        [
            line
            for line in DEFAULT_DATASET.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        ][0]
    )
    row["expected"][CONTROL_PROFILE] = "fit"
    dataset = tmp_path / "relabelled.jsonl"
    dataset.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="must be expected UNFIT"):
        load_cases(dataset)


def test_a_case_with_no_vertical_is_refused(tmp_path: Path) -> None:
    """Without a vertical there is no floor to measure the case against."""
    row = json.loads(
        [
            line
            for line in DEFAULT_DATASET.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        ][0]
    )
    row.pop("vertical")
    dataset = tmp_path / "no-vertical.jsonl"
    dataset.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="must name its vertical"):
        load_cases(dataset)


def test_a_case_missing_a_profile_narrative_is_refused(tmp_path: Path) -> None:
    row = json.loads(
        [
            line
            for line in DEFAULT_DATASET.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        ][0]
    )
    row["candidates"].pop(CONTROL_PROFILE)
    dataset = tmp_path / "no-control.jsonl"
    dataset.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="no narrative for"):
        load_cases(dataset)


# --------------------------------------------------------------------------- #
# Offline by default, end to end
# --------------------------------------------------------------------------- #
def test_the_check_passes_offline_with_no_model_server() -> None:
    """The load-bearing one: this is what CI runs, with no server, no network, no credentials."""
    assert main([]) == 0


def test_the_check_runs_with_every_socket_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proof rather than assurance: the offline path cannot open a connection, so it does not.

    "It works with no model server" is easy to believe on a laptop that happens to have one
    running, which is exactly the machine this was developed on. Blocking the socket
    constructor turns the claim into something a test can fail.
    """

    def _refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("the offline narrative check tried to open a socket")

    monkeypatch.setattr(socket, "socket", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)
    assert main([]) == 0


def test_a_stray_environment_variable_cannot_redirect_the_gate_to_a_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gate's judge comes from its flag, not from the environment it happened to inherit.

    A developer with the local-model variables exported for their own experiments must not turn
    the repository gate into something that needs a server, and a machine without that server
    must not fail a check it should have run offline.
    """
    monkeypatch.setenv(JUDGE_BACKEND_ENV, "local-model")
    monkeypatch.setenv(JUDGE_BASE_URL_ENV, "http://127.0.0.1:8001")
    monkeypatch.setenv(JUDGE_MODEL_ENV, "example/not-a-real-model")
    assert main([]) == 0


def test_the_default_selection_is_the_offline_judge() -> None:
    selection = JudgeSelection.from_env({})
    assert selection.is_offline is True
    assert isinstance(build_judge(selection), DeterministicNarrativeJudge)


def test_the_measured_profiles_are_the_two_a_buyer_chooses_between() -> None:
    assert MEASURED_PROFILES == ("managed", "reduced")
