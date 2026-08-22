"""EvaluationService : grounded model evaluation orchestration (SPEC §5).

Owns the evaluation pipeline and calls only ports. For a target and golden dataset it
produces an :class:`EvalReport` scoring the target on the model-risk metrics
(groundedness, citation_accuracy, faithfulness, safety). Grounded metrics pull the
reference context for each golden input from the A2 Enterprise KB
(``KnowledgeBaseClientPort``) so a groundedness judgement is traceable to a source.

Pipeline (SPEC §5), wrapped in ``tracer.span`` and audited:

    tracer.span("evaluation.evaluate"):
      empty dataset -> EmptyDatasetError (never a vacuous PASS)
      -> for each metric: pull A2 reference context, call the EvaluationPort
         (Gen AI evaluation service in gcp, deterministic backend in tests)
      -> assemble EvalReport (per-metric score / threshold / passed)
      -> audit.record(evaluate)

Defensive throughout: a backend that returns an unusable shape degrades to a failing
metric rather than crashing. Pure domain code : no Google Cloud / ADK imports.
"""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any
from uuid import uuid4

from . import _grounded as g
from .errors import AssurancePersistenceError, EmptyDatasetError
from .models import (
    AuditEvent,
    Decision,
    EvalDataset,
    EvalExampleEvidence,
    EvalMetricResult,
    EvalReport,
    EvalTarget,
    EvaluationOutcome,
)
from .thresholds import DEFAULT_METRICS, threshold_for


class EvaluationService:
    """Evaluate a target against a golden dataset. Signature fixed by SPEC §5."""

    def __init__(
        self,
        evaluation: Any,
        knowledge_base: Any,
        llm: Any,
        tracer: Any,
        audit: Any,
        metrics_store: Any | None = None,
    ) -> None:
        self._evaluation = evaluation
        self._knowledge_base = knowledge_base
        self._llm = llm
        self._tracer = tracer
        self._audit = audit
        self._metrics_store = metrics_store

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def evaluate(
        self,
        target: EvalTarget,
        dataset: EvalDataset,
        actor: str,
        metrics: tuple[str, ...] | None = None,
        thresholds: dict[str, float] | None = None,
    ) -> EvalReport:
        """Evaluate ``target`` against ``dataset`` for ``actor`` (SPEC §5).

        ``thresholds`` (a resolved ``{metric: bar}`` map, e.g. a vertical bundle) both
        selects the metrics and supplies each metric's per-bundle bar; when omitted, the
        ``metrics`` tuple (or the default set) is scored against the global registry bars.
        """
        span = self._tracer.span(
            "evaluation.evaluate", action="evaluate", actor=actor, target=target.ref
        )
        with span if span is not None else nullcontext():
            return self._evaluate_inner(target, dataset, actor, metrics, thresholds)

    # ------------------------------------------------------------------ #
    # Pipeline
    # ------------------------------------------------------------------ #
    def _evaluate_inner(
        self,
        target: EvalTarget,
        dataset: EvalDataset,
        actor: str,
        metrics: tuple[str, ...] | None,
        thresholds: dict[str, float] | None = None,
    ) -> EvalReport:
        # 1) An empty golden set must be a hard error, never a vacuous PASS.
        if dataset.n_examples == 0:
            self._write_audit(
                actor, target, Decision.ESCALATED, "evaluation refused: empty dataset"
            )
            raise EmptyDatasetError(f"golden dataset {dataset.id!r} has no examples")

        # A resolved threshold map defines both the metric set and each metric's bar.
        wanted = tuple(thresholds) if thresholds is not None else (metrics or DEFAULT_METRICS)

        # 2) Pull the A2 reference context once so grounded metrics are traceable.
        #    Best-effort: if A2 is unavailable the backend still scores, just without
        #    enriched reference context (the deterministic test backend ignores it).
        self._warm_reference_context(dataset)

        # 3) Delegate scoring to the EvaluationPort and map onto domain metric rows.
        results, example_evidence, artifact_refs = self._score(target, dataset, wanted, thresholds)
        report = EvalReport(
            target=target,
            results=results,
            n_examples=dataset.n_examples,
            run_id=str(uuid4()),
            dataset_version=dataset.version,
            dataset_digest=dataset.digest,
            evaluator=type(self._evaluation).__name__,
            artifact_refs=artifact_refs,
            example_evidence=example_evidence,
            attested=bool(getattr(self._evaluation, "attested", False)),
        )

        # 4) Audit the evaluation (PASS -> ALLOWED, FAIL -> BLOCKED).
        decision = Decision.ALLOWED if report.passed else Decision.BLOCKED
        summary = (
            f"evaluated {target.ref}: "
            f"{sum(1 for r in results if r.passed)}/{len(results)} metrics passed"
        )
        self._write_audit(
            actor,
            target,
            decision,
            summary,
            n=dataset.n_examples,
            run_id=report.run_id,
        )
        self._record_metrics(report)
        return report

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _warm_reference_context(self, dataset: EvalDataset) -> None:
        """Retrieve A2 reference context for each golden input (best-effort).

        This warms the injected ``knowledge_base`` port for traceability; the retrieved
        context is not returned. Under ``local`` the deterministic scorer self-grounds on
        its own KB index (see ``adapters.local.evaluation``), so this warm-up neither
        feeds nor overrides the score. In ``gcp`` the managed evaluator does its own
        grounding. The pull is therefore advisory (it exercises the grounding path and
        surfaces an unreachable KB early), never the source of the metric.
        """
        if self._knowledge_base is None:
            return
        try:
            for example in dataset.examples:
                self._knowledge_base.retrieve(example.input, top_k=5)
        except Exception:  # noqa: BLE001 - reference enrichment is best-effort
            return

    def _score(
        self,
        target: EvalTarget,
        dataset: EvalDataset,
        metrics: tuple[str, ...],
        thresholds: dict[str, float] | None = None,
    ) -> tuple[
        tuple[EvalMetricResult, ...],
        tuple[EvalExampleEvidence, ...],
        tuple[str, ...],
    ]:
        """Run the EvaluationPort and normalise its scores into metric rows.

        The port returns ``{metric: score}`` for the requested metrics. We compare each
        against its promotion threshold. A metric the backend did not score defaults to
        0.0 (a fail) rather than being silently dropped.

        ``NotImplementedError`` is allowed to propagate: it is the on-prem placeholder
        signalling "no evaluator wired up", which must surface as a clean profile error
        (the CLI maps it to exit code 2), never be disguised as a failing evaluation.
        Any *other* backend fault degrades to empty scores (a failing report, not a crash).
        """
        try:
            raw_outcome = self._evaluation.score(target, dataset, list(metrics))
        except NotImplementedError:
            raise
        except Exception:  # noqa: BLE001 - a backend fault is a failing report, not a crash
            raw_outcome = {}
        if isinstance(raw_outcome, EvaluationOutcome):
            scores = raw_outcome.scores
            example_evidence = raw_outcome.examples
            artifact_refs = raw_outcome.artifact_refs
        else:
            scores = raw_outcome if isinstance(raw_outcome, dict) else {}
            example_evidence = ()
            artifact_refs = ()

        rows: list[EvalMetricResult] = []
        for metric in metrics:
            threshold = thresholds[metric] if thresholds is not None else threshold_for(metric)
            score = g.clamp(scores.get(metric, 0.0))
            rows.append(
                EvalMetricResult(
                    metric=metric,
                    score=score,
                    threshold=threshold,
                    passed=score >= threshold,
                )
            )
        return tuple(rows), example_evidence, artifact_refs

    def _record_metrics(self, report: EvalReport) -> None:
        """Persist trend evidence before an evaluation can be used by a release gate."""
        if self._metrics_store is None:
            return
        try:
            self._metrics_store.record(report)
        except Exception as exc:  # noqa: BLE001 - fail closed at the assurance boundary
            raise AssurancePersistenceError(
                f"evaluation evidence was computed but metrics persistence failed: {exc}"
            ) from exc

    def _write_audit(
        self,
        actor: str,
        target: EvalTarget,
        decision: Decision,
        summary: str,
        n: int = 0,
        run_id: str | None = None,
    ) -> None:
        event = AuditEvent(
            action="evaluate",
            actor=actor,
            decision=decision,
            redacted_prompt=summary,
            redacted_response=target.ref,
            run_id=run_id,
            metadata={"target": target.ref, "n_examples": str(n)},
        )
        try:
            self._audit.record(event)
        except Exception as exc:  # noqa: BLE001 - convert adapter failure to domain contract
            raise AssurancePersistenceError(
                f"evaluation evidence was computed but immutable audit persistence failed: {exc}"
            ) from exc
