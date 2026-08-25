"""Domain models for the AI Quality & Model-Risk Platform (system A4).

This module is the heart of the hexagon. It has **no dependency on Google Cloud,
ADK, FastAPI, or any framework** : only the Python standard library. Every adapter
(GCP, remote-platform, or on-prem placeholder) speaks in terms of these types, which
is what lets the managed-service stack be swapped for an on-premise one without
touching domain logic (General Principle P-02, "no vendor lock-in / ports & adapters").

A4 is the **production promotion gate**: it evaluates a target (a model + prompt
version + dataset) against golden datasets, runs an adversarial red-team harness, and
emits a PASS/FAIL gate verdict together with the model-risk (MRM) evidence behind it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime

from hex_service_kit import StrEnum
from hex_service_kit.observability import TokenUsage as TokenUsage


def utcnow() -> datetime:
    """Timezone-aware UTC now : the single clock the domain uses."""
    return datetime.now(UTC)


# --------------------------------------------------------------------------- #
# Evaluation target
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class EvalTarget:
    """The unit A4 gates: a model + prompt version + golden dataset.

    A *target* uniquely identifies what is being promoted. The same physical model
    behind two prompt versions is two distinct targets, because the prompt is part of
    the model-risk surface (it shapes behaviour the gate must re-evaluate).
    """

    model: str  # e.g. "gemini-3.5-flash" or a fine-tuned resource name
    prompt_version: str  # the PromptVersion.version this target was evaluated under
    dataset_id: str  # the golden EvalDataset.id used as the bar
    system: str = ""  # the system / agent under test (e.g. "C1", "A2"), free text

    @property
    def ref(self) -> str:
        """A stable, human-readable target reference for gate lookups and audit."""
        return f"{self.model}@{self.prompt_version}:{self.dataset_id}"


# --------------------------------------------------------------------------- #
# Golden datasets
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class GoldenExample:
    """One graded example in a golden dataset.

    ``expected_points`` are the claims an answer should cover; ``must_cite_ids`` are
    the source ids a grounded answer must cite. Both drive the deterministic offline
    scorers and the LLM-judge metrics.
    """

    id: str
    input: str
    expected_points: tuple[str, ...] = ()
    must_cite_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EvalDataset:
    """A versioned golden dataset : the bar a target is measured against."""

    id: str
    examples: tuple[GoldenExample, ...] = ()
    version: str = "v1"

    @property
    def n_examples(self) -> int:
        return len(self.examples)

    @property
    def digest(self) -> str:
        payload = [
            {
                "id": item.id,
                "input": item.input,
                "expected_points": item.expected_points,
                "must_cite_ids": item.must_cite_ids,
            }
            for item in self.examples
        ]
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return "sha256:" + hashlib.sha256(encoded).hexdigest()


# --------------------------------------------------------------------------- #
# Retrieval & citation (grounded eval pulls reference context from A2)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class Citation:
    """Provenance for a retrieved reference passage used in grounded evaluation.

    For A4 a citation points at the reference context the A2 Enterprise KB returned
    for a golden input, so a groundedness/citation-accuracy judgement can be traced to
    the exact source the answer should have used.
    """

    source_id: str
    title: str = ""
    url: str = ""
    page: int | None = None
    snippet: str = ""
    score: float | None = None
    acl_tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class WebCitation:
    """Provenance for a public-web grounded fact (secondary, cross-border)."""

    title: str
    url: str
    snippet: str = ""


# --------------------------------------------------------------------------- #
# Generation (LLM) : the judge model for LLM-graded metrics
# --------------------------------------------------------------------------- #
class ThinkingLevel(StrEnum):
    MINIMAL = "minimal"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class LlmMessage:
    role: str  # "user" | "model" | "system"
    content: str


@dataclass(frozen=True, slots=True)
class LlmRequest:
    messages: tuple[LlmMessage, ...]
    system_instruction: str | None = None
    model: str | None = None  # None => adapter default from config
    thinking: ThinkingLevel = ThinkingLevel.MEDIUM
    temperature: float = 0.2
    max_output_tokens: int = 4096
    response_schema: dict | None = None  # JSON schema for structured output


# ``TokenUsage`` is not declared here. It is imported from :mod:`hex_service_kit.observability`
# (see the import block at the top of this module) and re-exported unchanged, because a local
# declaration of the same three int fields defaulting to zero is what every repo in the catalog
# hand-copies: a shared value type that never gets shared. The commons definition carries the
# whole shape (same names, same ``int`` types, same zero defaults, same ``frozen=True,
# slots=True``), so this module and its callers construct and serialize exactly what a local
# declaration would give them. The import stays stdlib-only: the tracer implementation lives
# behind the commons ``otel`` extra, never in this dependency path.


@dataclass(frozen=True, slots=True)
class LlmResponse:
    text: str
    usage: TokenUsage = field(default_factory=TokenUsage)
    model: str = ""
    web_citations: tuple[WebCitation, ...] = ()
    raw: dict | None = None


# --------------------------------------------------------------------------- #
# Evaluation reports (the EvalReport artifact) : A4 AI Quality concern
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class EvalMetricResult:
    """One metric's score against its threshold."""

    metric: str  # "groundedness" | "citation_accuracy" | "faithfulness" | "safety" | ...
    score: float
    threshold: float
    passed: bool


@dataclass(frozen=True, slots=True)
class EvalExampleEvidence:
    """Redacted, row-level evidence returned by an evaluation backend.

    The evidence intentionally excludes prompts and model responses. ``detail`` is reserved
    for a backend's short rubric/verdict explanation and must already be redacted by the
    adapter. This gives reviewers a failing-case pivot without copying sensitive content
    into the promotion artifact.
    """

    example_id: str
    metric: str
    score: float
    passed: bool
    detail: str = ""
    trace_ref: str | None = None


@dataclass(frozen=True, slots=True)
class EvaluationOutcome:
    """Portable result returned by rich evaluation adapters.

    Simple/offline adapters may continue returning ``dict[str, float]``. Managed adapters
    return this envelope so per-example verdicts and managed artifact references survive
    domain orchestration instead of being collapsed into averages.
    """

    scores: dict[str, float]
    examples: tuple[EvalExampleEvidence, ...] = ()
    artifact_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EvalReport:
    """Scores per metric for one target over one dataset (the first A4 artifact)."""

    target: EvalTarget
    results: tuple[EvalMetricResult, ...]
    n_examples: int = 0
    run_id: str = ""
    dataset_version: str = "v1"
    dataset_digest: str = ""
    evaluator: str = ""
    schema_version: str = "eval-run/v1"
    trace_id: str | None = None
    correlation_id: str | None = None
    artifact_refs: tuple[str, ...] = ()
    example_evidence: tuple[EvalExampleEvidence, ...] = ()
    attested: bool = False

    @property
    def passed(self) -> bool:
        return self.n_examples > 0 and bool(self.results) and all(r.passed for r in self.results)


# --------------------------------------------------------------------------- #
# Red-team harness (the RedTeamReport artifact)
# --------------------------------------------------------------------------- #
class RedTeamCategory(StrEnum):
    """Adversarial probe families the red-team harness exercises."""

    PROMPT_INJECTION = "prompt_injection"
    JAILBREAK = "jailbreak"
    PII_EXFIL = "pii_exfil"
    HARMFUL_CONTENT = "harmful_content"
    HALLUCINATION = "hallucination"


@dataclass(frozen=True, slots=True)
class RedTeamCase:
    """A single adversarial probe.

    ``expected_block`` is the safe outcome: True when a compliant target must refuse
    or block the probe, False for a hallucination probe where the target must instead
    decline to fabricate (the harness scores "did not hallucinate" as the pass).
    """

    id: str
    category: RedTeamCategory
    probe: str
    expected_block: bool = True


@dataclass(frozen=True, slots=True)
class RedTeamResult:
    """The outcome of one probe against a target."""

    case: RedTeamCase
    blocked: bool
    detail: str = ""
    passed: bool = False


@dataclass(frozen=True, slots=True)
class RedTeamReport:
    """Per-probe outcomes for one target (the second A4 artifact)."""

    target: EvalTarget
    results: tuple[RedTeamResult, ...]

    @property
    def passed(self) -> bool:
        return bool(self.results) and all(r.passed for r in self.results)

    @property
    def n_cases(self) -> int:
        return len(self.results)


# --------------------------------------------------------------------------- #
# Prompt versioning & model cards (MRM evidence)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class PromptVersion:
    """A versioned, checksummed prompt template (MRM change-control evidence)."""

    name: str
    version: str
    template: str
    created_at: datetime = field(default_factory=utcnow)
    checksum: str = ""


@dataclass(frozen=True, slots=True)
class ModelCard:
    """A model card capturing intended use, metrics and limitations (MRM evidence)."""

    model: str
    version: str
    intended_use: str
    metrics: dict[str, float] = field(default_factory=dict)
    limitations: tuple[str, ...] = ()
    mrm_evidence_refs: tuple[str, ...] = ()
    owner: str = "model-risk"
    created_at: datetime = field(default_factory=utcnow)

    @property
    def ref(self) -> str:
        """Stable model-card reference stored on a GateDecision."""
        return f"{self.model}@{self.version}"


@dataclass(frozen=True, slots=True)
class MrmEvidence:
    """Immutable, run-keyed promotion evidence suitable for independent verification."""

    run_id: str
    target: EvalTarget
    eval_report: EvalReport
    redteam_report: RedTeamReport
    passed: bool
    requires_human_review: bool
    caveats: tuple[str, ...]
    model_card_ref: str
    audit_event_id: str
    threshold_policy_digest: str
    created_at: datetime = field(default_factory=utcnow)
    schema_version: str = "mrm-evidence/v1"

    @property
    def ref(self) -> str:
        return f"/v1/mrm-evidence/{self.run_id}"


# --------------------------------------------------------------------------- #
# Severity & the promotion gate verdict (the GateDecision artifact)
# --------------------------------------------------------------------------- #
class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class GateDecision:
    """The promotion verdict for a target (the third A4 artifact).

    ``passed`` is True iff the EvalReport passed every metric **and** the RedTeamReport
    blocked every probe it had to. A borderline pass (close to a threshold) sets
    ``requires_human_review`` so a model-risk officer signs off (maker-checker, P-06).
    """

    target: EvalTarget
    eval_report: EvalReport
    redteam_report: RedTeamReport
    passed: bool
    model_card_ref: str = ""
    mrm_evidence_ref: str = ""
    requires_human_review: bool = False
    caveats: tuple[str, ...] = ()


# --------------------------------------------------------------------------- #
# Drift (A5 metrics-store / drift dashboards concern)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class DriftSignal:
    """A drift observation for a model metric over time (feeds A5 dashboards)."""

    model: str
    metric: str
    baseline: float
    current: float
    drift: float  # current - baseline
    status: str = "stable"  # "stable" | "warning" | "alert"


@dataclass(frozen=True, slots=True)
class DriftEscalation:
    """What a drift reading OWES a human. It never promotes and never demotes.

    The promotion gate is the only thing that decides a promotion, and a person runs it.
    This artifact only ever RAISES the bar: it can require a re-gate and a model-risk
    review, and it carries no field a caller could read as an approval. There is
    deliberately no ``passed`` here, and no verdict of any kind: a drift reading is
    evidence that the gate's answer may be stale, not a new answer.

    ``status`` is the worst status across :attr:`signals`, and two of its values exist
    because an absent or unreadable measurement must not be reported as a calm one:
    ``unmeasured`` when nothing was recorded at all, and ``unrecognised`` when a signal
    carries a status this deployment's policy does not know. Both escalate. See
    :mod:`model_quality_gate.domain.drift`.
    """

    model: str
    status: str
    requires_re_gate: bool
    requires_human_review: bool
    signals: tuple[DriftSignal, ...] = ()
    escalating_metrics: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    schema_version: str = "drift-escalation/v1"


# --------------------------------------------------------------------------- #
# Audit & observability : A5 Observability, Audit & FinOps concerns
# --------------------------------------------------------------------------- #
class Decision(StrEnum):
    ALLOWED = "allowed"  # gate PASS, auto-promotable
    BLOCKED = "blocked"  # gate FAIL, promotion denied
    ESCALATED = "escalated"  # routed to a human (maker-checker)


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """An immutable, WORM-stored record of one gate / eval / red-team action.

    A4 does not process customer PII (it evaluates models against datasets), so there
    is no PII-redaction step here as there is in a customer-facing assistant; the
    prompt/response fields carry the target ref and a verdict summary, not user data.
    """

    action: str  # "evaluate" | "redteam" | "gate" | "drift" | "version_prompt" | "model_card"
    actor: str  # authenticated user / service identity
    decision: Decision
    redacted_prompt: str  # short, already-safe description of the action / verdict
    redacted_response: str = ""  # target/evidence detail; never raw model/customer content
    citations: tuple[Citation, ...] = ()
    resource: str = "ai-quality"
    trace_id: str | None = None
    span_id: str | None = None
    correlation_id: str | None = None
    run_id: str | None = None
    event_id: str = ""
    schema_version: str = "audit-event/v2"
    timestamp: datetime = field(default_factory=utcnow)
    metadata: dict[str, str] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Governance : A3 Agent Registry & Governance concerns (A2A AgentCard)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class AgentSkill:
    id: str
    name: str
    description: str


@dataclass(frozen=True, slots=True)
class AgentCard:
    """Minimal A2A-style agent card published at /.well-known/agent-card.json."""

    name: str
    description: str
    url: str
    version: str
    skills: tuple[AgentSkill, ...] = ()
    provider: str = "model-quality-gate"


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """A governed, least-privilege tool exposed to the agent (typically via MCP)."""

    name: str
    description: str
    input_schema: dict = field(default_factory=dict)
