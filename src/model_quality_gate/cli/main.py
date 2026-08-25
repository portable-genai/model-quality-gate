"""``ai-quality`` : the Typer CLI for the A4 AI Quality & Model-Risk Platform.

This is a thin presentation layer over the domain services. It owns no business logic:
every command builds the wiring from :func:`model_quality_gate.config.build_container` and the
factory functions in :mod:`model_quality_gate.api.deps`, invokes one domain service, and
pretty-prints the result.

Design constraints honoured here:

* **Import-safe.** Importing this module (e.g. the ``[project.scripts]`` entry point, or
  ``--help``) must never pull in FastAPI, uvicorn, the Google Cloud SDKs, or even the
  domain services. All of those are imported *lazily inside command bodies*, so the
  on-prem/test profile : which installs no Google Cloud SDK : can still load the CLI.
* **Profile-aware.** ``AI_QUALITY_PROFILE`` selects the adapter stack. The ``onprem``
  profile binds placeholder adapters that raise ``NotImplementedError``; when a command
  trips one, the CLI fails clearly (exit code 2) with a message that names the migration
  target rather than dumping a traceback.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import typer

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..config import Container
    from ..domain.models import DriftEscalation, EvalReport, GateDecision, RedTeamReport

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=(
        "A4 AI Quality & Model-Risk Platform : the production-promotion eval / red-team "
        "gate and model-risk (MRM) evidence system, on the Gemini Enterprise Agent "
        "Platform (GCP region configurable; default us-central1)."
    ),
)

# Exit codes: 2 == the active profile cannot satisfy this command (e.g. on-prem stub);
# 1 == an unexpected adapter/runtime failure. 0 == success.
_PROFILE_EXIT = 2
_RUNTIME_EXIT = 1

_CLI_ACTOR = "cli:operator"


# --------------------------------------------------------------------------- #
# Wiring helpers (all imports lazy, so this module stays import-safe)
# --------------------------------------------------------------------------- #
def _container() -> Container:
    from ..config import build_container

    return build_container()


def _deps() -> Any:
    try:
        from ..api import deps  # type: ignore[attr-defined]
    except ImportError as exc:  # pragma: no cover - defensive wiring guard
        _fail(
            f"Service factories (model_quality_gate.api.deps) are unavailable: {exc}",
            code=_RUNTIME_EXIT,
        )
    return deps


def _fail(message: str, *, code: int = _RUNTIME_EXIT) -> Any:
    typer.secho(f"error: {message}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code)


def _run(action: str, fn: Any) -> Any:
    """Execute ``fn`` and translate adapter failures into clean CLI errors."""
    from ..config import Settings

    profile = Settings.load().profile
    try:
        return fn()
    except NotImplementedError as exc:
        detail = str(exc) or "method not implemented"
        _fail(
            f"'{action}' is not available under profile '{profile}'. "
            f"This profile uses placeholder adapters (on-prem migration target): {detail}",
            code=_PROFILE_EXIT,
        )
    except KeyError as exc:
        _fail(f"'{action}' has no adapter wired for profile '{profile}': {exc}", code=_PROFILE_EXIT)
    except typer.Exit:
        raise
    except Exception as exc:  # noqa: BLE001 - CLI boundary: no tracebacks to operators
        _fail(f"'{action}' failed: {type(exc).__name__}: {exc}", code=_RUNTIME_EXIT)


# --------------------------------------------------------------------------- #
# Pretty-printing
# --------------------------------------------------------------------------- #
def _print_eval_report(report: EvalReport) -> None:
    verdict = "PASS" if report.passed else "FAIL"
    color = typer.colors.GREEN if report.passed else typer.colors.RED
    typer.secho(f"Eval report : {report.target.ref}  [{verdict}]", bold=True, fg=color)
    typer.echo(f"  examples: {report.n_examples}")
    for r in report.results:
        mark = "ok " if r.passed else "FAIL"
        line = f"  [{mark}] {r.metric:<18} {r.score:6.3f}  (threshold {r.threshold:.2f})"
        typer.secho(line, fg=typer.colors.GREEN if r.passed else typer.colors.RED)


def _print_redteam_report(report: RedTeamReport) -> None:
    verdict = "PASS" if report.passed else "FAIL"
    color = typer.colors.GREEN if report.passed else typer.colors.RED
    typer.secho(f"Red-team report : {report.target.ref}  [{verdict}]", bold=True, fg=color)
    for r in report.results:
        mark = "safe " if r.passed else "UNSAFE"
        typer.secho(
            f"  [{mark}] {r.case.category.value:<18} blocked={str(r.blocked).lower()}  {r.detail}",
            fg=typer.colors.GREEN if r.passed else typer.colors.RED,
        )


def _print_drift(escalation: DriftEscalation) -> None:
    calm = not escalation.requires_human_review
    typer.secho(
        f"Quality drift : {escalation.model}  [{escalation.status.upper()}]",
        bold=True,
        fg=typer.colors.GREEN if calm else typer.colors.YELLOW,
    )
    for signal in escalation.signals:
        mark = "ok " if signal.status == "stable" else signal.status.upper()
        typer.secho(
            f"  [{mark}] {signal.metric:<18} {signal.current:6.3f}  "
            f"(baseline {signal.baseline:.3f}, drift {signal.drift:+.3f})",
            fg=typer.colors.GREEN if signal.status == "stable" else typer.colors.YELLOW,
        )
    if escalation.requires_re_gate:
        typer.secho(
            "  [RE-GATE REQUIRED] a model-risk officer must re-run the promotion gate "
            "before this model's last verdict may still be relied on. Nothing was "
            "promoted or demoted by this command.",
            fg=typer.colors.YELLOW,
            bold=True,
        )
    for reason in escalation.reasons:
        typer.echo(f"  {reason}")


def _print_gate_decision(decision: GateDecision) -> None:
    verdict = "PASS" if decision.passed else "FAIL"
    color = typer.colors.GREEN if decision.passed else typer.colors.RED
    typer.secho(f"Promotion gate : {decision.target.ref}  [{verdict}]", bold=True, fg=color)
    typer.echo(f"  model card : {decision.model_card_ref}")
    typer.echo(f"  MRM evidence: {decision.mrm_evidence_ref}")
    if decision.requires_human_review:
        typer.secho(
            "  [HUMAN REVIEW REQUIRED] maker-checker gate (P-06): a model-risk officer "
            "must sign off before promotion.",
            fg=typer.colors.YELLOW,
            bold=True,
        )
    for caveat in decision.caveats:
        typer.secho(f"  caveat: {caveat}", fg=typer.colors.YELLOW)
    typer.echo("")
    _print_eval_report(decision.eval_report)
    _print_redteam_report(decision.redteam_report)


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
@app.command()
def evaluate(
    model: str = typer.Argument(..., help="Model under evaluation (e.g. gemini-3.5-flash)."),
    prompt_version: str = typer.Argument(..., help="Prompt version label (e.g. v3)."),
    dataset_id: str = typer.Argument(..., help="Golden dataset id to evaluate against."),
) -> None:
    """Evaluate a target against a golden dataset on the model-risk metrics."""

    def _do() -> EvalReport:
        from ..domain.models import EvalTarget
        from ..pipelines.datasets import load_golden_dataset

        svc = _deps().build_evaluation_service(_container())
        target = EvalTarget(model=model, prompt_version=prompt_version, dataset_id=dataset_id)
        return svc.evaluate(target, load_golden_dataset(dataset_id), actor=_CLI_ACTOR)

    _print_eval_report(_run("evaluate", _do))


@app.command()
def redteam(
    model: str = typer.Argument(..., help="Model under test."),
    prompt_version: str = typer.Argument(..., help="Prompt version label."),
) -> None:
    """Run the adversarial red-team harness against a target."""

    def _do() -> RedTeamReport:
        from ..domain.models import EvalTarget
        from ..pipelines.datasets import standard_redteam_cases

        svc = _deps().build_redteam_service(_container())
        target = EvalTarget(model=model, prompt_version=prompt_version, dataset_id="")
        return svc.run(target, standard_redteam_cases(), actor=_CLI_ACTOR)

    _print_redteam_report(_run("redteam", _do))


@app.command()
def gate(
    model: str = typer.Argument(..., help="Model under evaluation."),
    prompt_version: str = typer.Argument(..., help="Prompt version label."),
    dataset_id: str = typer.Argument(..., help="Golden dataset id to gate against."),
) -> None:
    """Run the full PASS/FAIL promotion gate (eval AND red-team) for a target."""

    def _do() -> GateDecision:
        from ..domain.models import EvalTarget
        from ..pipelines.datasets import load_golden_dataset, standard_redteam_cases

        svc = _deps().build_gate_service(_container())
        target = EvalTarget(model=model, prompt_version=prompt_version, dataset_id=dataset_id)
        return svc.gate(
            target, load_golden_dataset(dataset_id), standard_redteam_cases(), actor=_CLI_ACTOR
        )

    decision = _run("gate", _do)
    _print_gate_decision(decision)
    raise typer.Exit(0 if decision.passed else 1)


@app.command()
def drift(
    model: str = typer.Argument(..., help="Model whose recorded quality drift to read."),
) -> None:
    """Report a model's recorded quality drift and what it owes a model-risk officer.

    Exits 1 when a re-gate is required, so a monitor can page on it. The non-zero exit is
    a SIGNAL: this command runs no gate, promotes nothing and demotes nothing.
    """

    def _do() -> DriftEscalation:
        svc = _deps().build_drift_service(_container())
        return svc.assess(model, actor=_CLI_ACTOR)

    escalation = _run("drift", _do)
    _print_drift(escalation)
    raise typer.Exit(1 if escalation.requires_re_gate else 0)


@app.command(name="version-prompt")
def version_prompt(
    name: str = typer.Argument(..., help="Logical prompt name (e.g. compliance-qa)."),
    version: str = typer.Argument(..., help="Version label (e.g. v3)."),
    template: str = typer.Argument(..., help="Prompt template text."),
) -> None:
    """Register a versioned, checksummed prompt (MRM change-control evidence)."""

    def _do() -> Any:
        from ..domain.models import PromptVersion

        svc = _deps().build_prompt_service(_container())
        stored = svc.register(
            PromptVersion(name=name, version=version, template=template), actor=_CLI_ACTOR
        )
        return stored

    stored = _run("version-prompt", _do)
    typer.secho(
        f"registered prompt {stored.name}@{stored.version} (checksum {stored.checksum})",
        fg=typer.colors.GREEN,
        bold=True,
    )


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind address for the API server."),
    port: int = typer.Option(8084, help="TCP port for the API server."),
    reload: bool = typer.Option(False, "--reload", help="Auto-reload on code change (dev only)."),
) -> None:
    """Run the FastAPI app (A2A card, MCP, and REST endpoints) under uvicorn."""

    def _do() -> None:
        import uvicorn

        deps = _deps()
        if not hasattr(deps, "create_app"):
            _fail(
                "model_quality_gate.api.deps does not expose create_app(); "
                "cannot start the server.",
                code=_RUNTIME_EXIT,
            )
        typer.secho(
            f"serving ai-quality on http://{host}:{port} (profile={_profile_label()})",
            fg=typer.colors.GREEN,
        )
        uvicorn.run(
            "model_quality_gate.api.deps:create_app",
            factory=True,
            host=host,
            port=port,
            reload=reload,
        )

    _run("serve", _do)


@app.command(name="eval")
def eval_gate(
    dataset: str | None = typer.Option(
        None, "--dataset", "-d", help="Path to the golden gate-logic dataset (defaults bundled)."
    ),
) -> None:
    """Run the A4 self-eval gate (validates the gate logic: gate_accuracy, etc.).

    Delegates to ``eval/run_eval.py`` in a subprocess so the heavy Gen AI evaluation
    dependencies stay out of the CLI's import graph. The subprocess's exit code is the
    gate verdict and becomes this command's exit code.
    """

    def _do() -> int:
        import subprocess
        import sys
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[3]
        script = repo_root / "eval" / "run_eval.py"
        if not script.exists():
            _fail(f"eval gate script not found at {script}", code=_RUNTIME_EXIT)
        cmd = [sys.executable, str(script)]
        if dataset:
            cmd += ["--dataset", dataset]
        typer.secho(f"running self-eval gate: {script}", fg=typer.colors.CYAN)
        completed = subprocess.run(cmd, check=False)  # noqa: S603 - trusted local script
        return completed.returncode

    code = _run("eval", _do)
    if code == 0:
        typer.secho("self-eval gate: PASS", fg=typer.colors.GREEN, bold=True)
    else:
        typer.secho("self-eval gate: FAIL", fg=typer.colors.RED, bold=True)
    raise typer.Exit(int(code))


def _profile_label() -> str:
    from ..config import Settings

    return Settings.load().profile


if __name__ == "__main__":  # pragma: no cover
    app()
