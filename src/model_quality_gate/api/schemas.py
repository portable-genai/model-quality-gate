"""Pydantic v2 request/response models for the A4 AI Quality & Model-Risk API.

These schemas mirror the frozen domain dataclasses in :mod:`model_quality_gate.domain.models`
one-for-one, so the HTTP boundary is a thin, typed projection of the domain : the
React/Next.js UI, the CLI, and sibling repos (which consume the A4 gate contract) all
speak exactly these shapes. Each response model exposes a ``from_domain`` classmethod that
builds itself from the corresponding domain object (enums become their ``.value`` strings).

Nothing here imports Google Cloud, ADK, or any adapter: the API layer depends only on the
domain models, the ports, and the orchestration services : never on a concrete adapter.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

from ..domain import models as m
from ..domain.serialization import to_jsonable

# --------------------------------------------------------------------------- #
# Requests
# --------------------------------------------------------------------------- #


class TargetModel(BaseModel):
    """A target under evaluation (mirror of EvalTarget)."""

    model: str = Field(..., min_length=1)
    prompt_version: str = Field(..., min_length=1)
    dataset_id: str = Field(..., min_length=1)
    system: str = ""

    def to_domain(self) -> m.EvalTarget:
        return m.EvalTarget(
            model=self.model,
            prompt_version=self.prompt_version,
            dataset_id=self.dataset_id,
            system=self.system,
        )


class _DatasetIdConsistency(BaseModel):
    """Mixin: refuse a request whose top-level ``dataset_id`` diverges from the target's.

    The top-level id is the source of truth (it loads the data). ``target.dataset_id``
    only decorates the audit ref, so a divergence is a caller error, refused fail-closed
    (WP-D) rather than silently resolved.
    """

    target: TargetModel
    dataset_id: str

    @model_validator(mode="after")
    def _dataset_ids_agree(self) -> _DatasetIdConsistency:
        # ValueError (pydantic idiom) so FastAPI returns 422, not 500.
        if self.target.dataset_id != self.dataset_id:
            raise ValueError(
                f"dataset_id {self.dataset_id!r} != target.dataset_id "
                f"{self.target.dataset_id!r}; the top-level id is authoritative"
            )
        return self


class EvaluateRequest(_DatasetIdConsistency):
    """Inbound evaluation request.

    No ``actor`` field: the audit actor is the server-verified :class:`Principal`
    (see ``api/security.py``), never a client-supplied value. A caller selects metrics by
    naming a registered ``bundle`` (preferred) or an explicit ``metrics`` list; unknown
    names are rejected 422 (never silently passed).
    """

    target: TargetModel
    dataset_id: str = Field(..., min_length=1, description="Golden dataset to evaluate against.")
    bundle: str | None = Field(default=None, description="Registered metric bundle name.")
    metrics: list[str] | None = Field(default=None, description="Optional explicit metric subset.")


class DatasetIngestRequest(BaseModel):
    """Publish a golden dataset as JSONL text (WP-C).

    The payload is stored verbatim; it is parsed once to reject a set with no examples
    (a golden set that would produce a vacuous gate).
    """

    dataset_id: str = Field(..., min_length=1)
    jsonl: str = Field(..., min_length=1, description="Golden set as JSONL text.")


class DatasetSummaryModel(BaseModel):
    """A stored golden dataset (id + example count), never its raw contents."""

    dataset_id: str
    n_examples: int


class RedTeamRequest(BaseModel):
    """Inbound red-team request."""

    target: TargetModel
    categories: list[str] | None = Field(
        default=None, description="Optional probe-category subset (defaults to all)."
    )


class GateRequest(_DatasetIdConsistency):
    """Inbound promotion-gate request."""

    target: TargetModel
    dataset_id: str = Field(..., min_length=1)
    bundle: str | None = Field(default=None, description="Registered metric bundle name.")
    metrics: list[str] | None = Field(default=None, description="Optional explicit metric subset.")


class PromptVersionRequest(BaseModel):
    """Inbound prompt-version registration."""

    version: str = Field(..., min_length=1)
    template: str = Field(..., min_length=1)


# --------------------------------------------------------------------------- #
# Responses
# --------------------------------------------------------------------------- #


class EvalMetricResultModel(BaseModel):
    metric: str
    score: float
    threshold: float
    passed: bool

    @classmethod
    def from_domain(cls, result: m.EvalMetricResult) -> EvalMetricResultModel:
        return cls(**to_jsonable(result))


class EvalExampleEvidenceModel(BaseModel):
    example_id: str
    metric: str
    score: float
    passed: bool
    detail: str = ""
    trace_ref: str | None = None


class EvalReportModel(BaseModel):
    """Scores per metric for one target (mirror of EvalReport)."""

    target: dict[str, Any]
    results: list[EvalMetricResultModel] = Field(default_factory=list)
    n_examples: int = 0
    passed: bool = False
    run_id: str = ""
    dataset_version: str = "v1"
    dataset_digest: str = ""
    evaluator: str = ""
    schema_version: str = "eval-run/v1"
    trace_id: str | None = None
    correlation_id: str | None = None
    artifact_refs: list[str] = Field(default_factory=list)
    example_evidence: list[EvalExampleEvidenceModel] = Field(default_factory=list)
    attested: bool = False

    @classmethod
    def from_domain(cls, report: m.EvalReport) -> EvalReportModel:
        return cls(
            target=to_jsonable(report.target),
            results=[EvalMetricResultModel.from_domain(r) for r in report.results],
            n_examples=report.n_examples,
            passed=report.passed,
            run_id=report.run_id,
            dataset_version=report.dataset_version,
            dataset_digest=report.dataset_digest,
            evaluator=report.evaluator,
            schema_version=report.schema_version,
            trace_id=report.trace_id,
            correlation_id=report.correlation_id,
            artifact_refs=list(report.artifact_refs),
            example_evidence=[
                EvalExampleEvidenceModel(**to_jsonable(item)) for item in report.example_evidence
            ],
            attested=report.attested,
        )


class RedTeamResultModel(BaseModel):
    category: str
    probe_id: str
    blocked: bool
    passed: bool
    detail: str = ""

    @classmethod
    def from_domain(cls, result: m.RedTeamResult) -> RedTeamResultModel:
        return cls(
            category=result.case.category.value,
            probe_id=result.case.id,
            blocked=result.blocked,
            passed=result.passed,
            detail=result.detail,
        )


class RedTeamReportModel(BaseModel):
    """Per-probe outcomes for one target (mirror of RedTeamReport)."""

    target: dict[str, Any]
    results: list[RedTeamResultModel] = Field(default_factory=list)
    passed: bool = False

    @classmethod
    def from_domain(cls, report: m.RedTeamReport) -> RedTeamReportModel:
        return cls(
            target=to_jsonable(report.target),
            results=[RedTeamResultModel.from_domain(r) for r in report.results],
            passed=report.passed,
        )


class GateDecisionModel(BaseModel):
    """The promotion verdict (mirror of GateDecision)."""

    target: dict[str, Any]
    eval_report: EvalReportModel
    redteam_report: RedTeamReportModel
    passed: bool
    model_card_ref: str = ""
    mrm_evidence_ref: str = ""
    requires_human_review: bool = False
    caveats: list[str] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, decision: m.GateDecision) -> GateDecisionModel:
        return cls(
            target=to_jsonable(decision.target),
            eval_report=EvalReportModel.from_domain(decision.eval_report),
            redteam_report=RedTeamReportModel.from_domain(decision.redteam_report),
            passed=decision.passed,
            model_card_ref=decision.model_card_ref,
            mrm_evidence_ref=decision.mrm_evidence_ref,
            requires_human_review=decision.requires_human_review,
            caveats=list(decision.caveats),
        )


class GateStatusResponse(BaseModel):
    """The cheap ``GET /v1/gate`` verdict (just whether the target passed)."""

    passed: bool


class DriftSignalModel(BaseModel):
    """One metric's movement away from its baseline (mirror of DriftSignal)."""

    model: str
    metric: str
    baseline: float
    current: float
    drift: float
    status: str

    @classmethod
    def from_domain(cls, signal: m.DriftSignal) -> DriftSignalModel:
        return cls(**to_jsonable(signal))


class DriftEscalationModel(BaseModel):
    """What a drift reading owes a human (mirror of DriftEscalation).

    There is no verdict field here and there is not meant to be one. The response states a
    requirement (re-gate, review) and never an approval, so a consumer cannot read a calm
    drift reading as a promotion.
    """

    model: str
    status: str
    requires_re_gate: bool
    requires_human_review: bool
    signals: list[DriftSignalModel] = Field(default_factory=list)
    escalating_metrics: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    schema_version: str = "drift-escalation/v1"

    @classmethod
    def from_domain(cls, escalation: m.DriftEscalation) -> DriftEscalationModel:
        return cls(
            model=escalation.model,
            status=escalation.status,
            requires_re_gate=escalation.requires_re_gate,
            requires_human_review=escalation.requires_human_review,
            signals=[DriftSignalModel.from_domain(s) for s in escalation.signals],
            escalating_metrics=list(escalation.escalating_metrics),
            reasons=list(escalation.reasons),
            schema_version=escalation.schema_version,
        )


class PromptVersionModel(BaseModel):
    name: str
    version: str
    template: str
    checksum: str
    created_at: str

    @classmethod
    def from_domain(cls, version: m.PromptVersion) -> PromptVersionModel:
        return cls(**to_jsonable(version))


class ModelCardModel(BaseModel):
    model: str
    version: str
    intended_use: str
    metrics: dict[str, float] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    mrm_evidence_refs: list[str] = Field(default_factory=list)
    owner: str = "model-risk"
    created_at: str

    @classmethod
    def from_domain(cls, card: m.ModelCard) -> ModelCardModel:
        return cls(**to_jsonable(card))


class HealthResponse(BaseModel):
    """Liveness/readiness of the service and its active profile."""

    #: Provenance the UI banner states on every page: where the runtime sits and which
    #: model answers. Derived server-side so the console never guesses (org decision,
    #: 2026-08-30).
    runtime: str = "local"  # "gcp" | "local"
    generator_model: str = "deterministic-offline-stub"

    status: str = "ok"
    profile: str = "local"
    region: str = "asia-southeast1"
    production_ready: bool = False
    demo_only: bool = True


class CapabilityModel(BaseModel):
    name: str
    available: bool
    mode: str
    assurance: str
    provider: str = ""
    reason: str = ""
    required_for_production: bool = False


class CapabilityManifestModel(BaseModel):
    service: str
    profile: str
    region: str
    capabilities: list[CapabilityModel]
    schema_version: str = "capability-manifest/v1"
    portable_core: bool = True
    demo_only: bool = False
    production_ready: bool = False


class AgentSkillModel(BaseModel):
    id: str
    name: str
    description: str


class AgentCardModel(BaseModel):
    """A2A AgentCard served at /.well-known/agent-card.json (mirror of AgentCard)."""

    name: str
    description: str
    url: str
    version: str
    provider: str = "model-quality-gate"
    skills: list[AgentSkillModel] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, card: m.AgentCard) -> AgentCardModel:
        data: dict[str, Any] = to_jsonable(card)
        return cls(**data)
