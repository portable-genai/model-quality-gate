"""Pytest fixtures: the ``local`` adapters (seeded) + assembled domain services.

The unit suite is driven by the **real** ``local`` adapter family
(``src/model_quality_gate/adapters/local``) rather than bespoke in-memory fakes, so the offline
implementation lives in exactly one place and the tests exercise the same code the offline
CLI runs. Every adapter constructs with a single ``Settings`` (the adapter convention)
pointed at ``:memory:`` SQLite, and the knowledge-base index is seeded with the synthetic
``tests/fixtures/sample_targets`` citations for determinism.

A few fixtures wrap the local adapter in a thin **recording** subclass that captures call
arguments for assertions (``.calls`` / ``.requests`` / ``.spans`` / ``.events`` / ``.puts``).
These add no behaviour: every method delegates to the real local adapter, so the in-memory
implementation is still the one under ``adapters/local``. The recorders are the test
instrumentation the previous bespoke fakes used to bundle.

Toggling the FAIL paths is done by driving the real local adapters with the appropriate
input or with a small seed knob expressed as a *thin local subclass*
(``FixedEvaluation`` / ``UnsafeRedTeam``), not by swapping in a separate fake hierarchy.
"""

from __future__ import annotations

import importlib
import os

# The dev / test profile is ``local`` (the SDK-free offline stack), and the suite says so
# DELIBERATELY: ``config.resolve_profile`` treats an unset AI_QUALITY_PROFILE as "nobody chose",
# which withholds the three relaxations ``local`` is granted (the zero-secret S2S opening, the
# localhost CORS dev origins, and the omission of HSTS). Setting it here is the same explicit
# choice the Makefile and ci.yaml make, and it makes the suite hermetic under a bare ``pytest``
# invocation. ``setdefault`` so an outer AI_QUALITY_PROFILE still wins.
# ``tests/unit/test_profile_single_source.py`` proves the unset behaviour independently, by
# passing an explicit environment mapping to the resolver.
os.environ.setdefault("AI_QUALITY_PROFILE", "local")

from typing import Any  # noqa: E402

import pytest  # noqa: E402

#: A loopback peer for every ``TestClient``. The app-object exposure guard refuses the
#: unauthenticated ``local`` posture to any other peer, and TestClient's DEFAULT peer is the
#: literal host ``"testclient"``, which is not a loopback address and is refused with a 503.
LOOPBACK_PEER = ("127.0.0.1", 50000)

from model_quality_gate.adapters.local.audit import LocalAppendOnlyAuditAdapter  # noqa: E402
from model_quality_gate.adapters.local.evaluation import LocalDeterministicEvalAdapter  # noqa: E402
from model_quality_gate.adapters.local.knowledge_base import (  # noqa: E402
    LocalFtsKnowledgeBaseAdapter,
)
from model_quality_gate.adapters.local.llm import LocalDeterministicLLMAdapter  # noqa: E402
from model_quality_gate.adapters.local.metrics_store import LocalMetricsStoreAdapter  # noqa: E402
from model_quality_gate.adapters.local.model_card_store import (  # noqa: E402
    LocalModelCardStoreAdapter,
)
from model_quality_gate.adapters.local.prompt_registry import (  # noqa: E402
    LocalPromptRegistryAdapter,
)
from model_quality_gate.adapters.local.redteam import LocalHeuristicRedTeamAdapter  # noqa: E402
from model_quality_gate.adapters.local.registry import LocalRegistryAdapter  # noqa: E402
from model_quality_gate.adapters.local.tool_catalog import LocalToolCatalogAdapter  # noqa: E402
from model_quality_gate.adapters.local.tracer import LocalNoopTracerAdapter  # noqa: E402
from model_quality_gate.config import LocalSettings, Settings  # noqa: E402
from model_quality_gate.domain.models import (  # noqa: E402
    AuditEvent,
    Citation,
    EvalDataset,
    EvalTarget,
    LlmRequest,
    LlmResponse,
    ModelCard,
    RedTeamCase,
    RedTeamReport,
    RedTeamResult,
)
from tests.fixtures import sample_targets  # noqa: E402


def make_local_settings() -> Settings:
    """Settings whose local stores are ephemeral in-memory SQLite (deterministic)."""
    return Settings(
        profile="local",
        local=LocalSettings(
            db_path=":memory:",
            audit_path=":memory:",
            registry_path=":memory:",
            model_cards_path=":memory:",
            metrics_path=":memory:",
        ),
    )


# Internal alias used by the fixtures below.
_settings = make_local_settings


# --------------------------------------------------------------------------- #
# Recording wrappers : thin subclasses of the local adapters that capture call
# arguments for assertions. Every method delegates to the real local adapter.
# --------------------------------------------------------------------------- #
class RecordingEvaluation(LocalDeterministicEvalAdapter):
    """Local deterministic evaluation scorer that records the score calls it received."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.calls: list[tuple[EvalTarget, list[str]]] = []

    def score(
        self, target: EvalTarget, dataset: EvalDataset, metrics: list[str]
    ) -> dict[str, float]:
        self.calls.append((target, list(metrics)))
        return super().score(target, dataset, metrics)


class FixedEvaluation(LocalDeterministicEvalAdapter):
    """Local scorer with fixed per-metric overrides, to drive PASS / FAIL / borderline.

    A thin behavioural variant of the real local scorer: it lets a test pin specific
    metric scores (a failing safety score, a borderline groundedness) without inventing a
    separate fake. Unpinned metrics fall back to ``passing_score``.
    """

    def __init__(
        self,
        settings: Settings,
        passing_score: float = 1.0,
        overrides: dict[str, float] | None = None,
    ) -> None:
        super().__init__(settings)
        self._passing_score = passing_score
        self._overrides = dict(overrides or {})
        self.calls: list[tuple[EvalTarget, list[str]]] = []

    def score(
        self, target: EvalTarget, dataset: EvalDataset, metrics: list[str]
    ) -> dict[str, float]:
        self.calls.append((target, list(metrics)))
        return {m: self._overrides.get(m, self._passing_score) for m in metrics}


class RecordingRedTeam(LocalHeuristicRedTeamAdapter):
    """Local heuristic red-team harness that records the (target, cases) run calls."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.calls: list[tuple[EvalTarget, list[RedTeamCase]]] = []

    def run(self, target: EvalTarget, cases: list[RedTeamCase]) -> RedTeamReport:
        self.calls.append((target, list(cases)))
        return super().run(target, cases)


class UnsafeRedTeam(LocalHeuristicRedTeamAdapter):
    """Local red-team harness forced to report every probe as not safely handled.

    Drives the gate FAIL path. It reuses the real adapter's shape (RedTeamReport of
    RedTeamResult) so it is a thin behavioural variant, not a separate fake hierarchy.
    """

    def run(self, target: EvalTarget, cases: list[RedTeamCase]) -> RedTeamReport:
        results = tuple(
            RedTeamResult(case=case, blocked=False, detail="forced unhandled", passed=False)
            for case in cases
        )
        return RedTeamReport(target=target, results=results)


class RecordingLLM(LocalDeterministicLLMAdapter):
    """Local deterministic judge LLM that records the requests it received."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.requests: list[LlmRequest] = []

    def generate(self, request: LlmRequest) -> LlmResponse:
        self.requests.append(request)
        return super().generate(request)


class RecordingKnowledgeBase(LocalFtsKnowledgeBaseAdapter):
    """Local FTS5 knowledge base that records the queries it received (seeded corpus)."""

    def __init__(self, settings: Settings, citations: list[Citation] | None = None) -> None:
        super().__init__(settings)
        # Re-seed the in-memory index with the requested corpus for determinism.
        self.seed(list(sample_targets.SAMPLE_CITATIONS) if citations is None else list(citations))
        self.calls: list[str] = []

    def retrieve(self, query: str, top_k: int = 5) -> list[Citation]:
        self.calls.append(query)
        return super().retrieve(query, top_k)


class RecordingTracer(LocalNoopTracerAdapter):
    """Local no-op tracer that records the span names it opened."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.spans: list[str] = []

    def span(self, name: str, **attributes: str):  # type: ignore[no-untyped-def]
        self.spans.append(name)
        return super().span(name, **attributes)


class RecordingAudit(LocalAppendOnlyAuditAdapter):
    """Local append-only audit that also keeps the AuditEvent objects for assertions."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.events: list[AuditEvent] = []

    def record(self, event: AuditEvent) -> str:
        self.events.append(event)
        return super().record(event)


class RecordingModelCardStore(LocalModelCardStoreAdapter):
    """Local model-card store that also keeps the cards it persisted for assertions."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.puts: list[ModelCard] = []

    def put(self, card: ModelCard) -> None:
        self.puts.append(card)
        super().put(card)


# --------------------------------------------------------------------------- #
# Service / policy resolvers : locate the domain classes wherever they live.
# --------------------------------------------------------------------------- #
_SERVICE_MODULE_CANDIDATES = (
    "model_quality_gate.domain.evaluation_service",
    "model_quality_gate.domain.redteam_service",
    "model_quality_gate.domain.gate_service",
    "model_quality_gate.domain.prompt_service",
    "model_quality_gate.domain.model_card_service",
    "model_quality_gate.domain.services",
)
_POLICY_MODULE_CANDIDATES = (
    "model_quality_gate.domain.hitl",
    "model_quality_gate.domain.thresholds",
    "model_quality_gate.domain.services",
)


def _resolve(symbol: str, candidates: tuple[str, ...]) -> Any:
    last: Exception | None = None
    for mod_name in candidates:
        try:
            module = importlib.import_module(mod_name)
        except ModuleNotFoundError as exc:  # pragma: no cover - layout fallback
            last = exc
            continue
        obj = getattr(module, symbol, None)
        if obj is not None:
            return obj
    raise ImportError(f"Could not locate domain symbol {symbol!r} in any of {candidates}") from last


def load_service(name: str) -> Any:
    return _resolve(name, _SERVICE_MODULE_CANDIDATES)


def load_policy(name: str) -> Any:
    return _resolve(name, _POLICY_MODULE_CANDIDATES)


# --------------------------------------------------------------------------- #
# Pytest fixtures : construct the (seeded) local adapters.
# --------------------------------------------------------------------------- #
@pytest.fixture
def local_settings() -> Settings:
    """In-memory local Settings for tests that construct a thin local adapter directly."""
    return make_local_settings()


@pytest.fixture
def evaluation() -> RecordingEvaluation:
    return RecordingEvaluation(_settings())


@pytest.fixture
def redteam() -> RecordingRedTeam:
    return RecordingRedTeam(_settings())


@pytest.fixture
def llm() -> RecordingLLM:
    return RecordingLLM(_settings())


@pytest.fixture
def knowledge_base() -> RecordingKnowledgeBase:
    return RecordingKnowledgeBase(_settings())


@pytest.fixture
def prompt_registry() -> LocalPromptRegistryAdapter:
    return LocalPromptRegistryAdapter(_settings())


@pytest.fixture
def model_card_store() -> RecordingModelCardStore:
    return RecordingModelCardStore(_settings())


@pytest.fixture
def metrics_store() -> LocalMetricsStoreAdapter:
    return LocalMetricsStoreAdapter(_settings())


@pytest.fixture
def tracer() -> RecordingTracer:
    return RecordingTracer(_settings())


@pytest.fixture
def audit() -> RecordingAudit:
    return RecordingAudit(_settings())


@pytest.fixture
def registry() -> LocalRegistryAdapter:
    return LocalRegistryAdapter(_settings())


@pytest.fixture
def tool_catalog() -> LocalToolCatalogAdapter:
    return LocalToolCatalogAdapter(_settings())


@pytest.fixture
def evaluation_service(evaluation, knowledge_base, llm, tracer, audit, metrics_store):
    """EvaluationService with durable local evaluation evidence."""
    cls = load_service("EvaluationService")
    return cls(evaluation, knowledge_base, llm, tracer, audit, metrics_store)


@pytest.fixture
def redteam_service(redteam, tracer, audit):
    """RedTeamService(redteam, tracer, audit)."""
    cls = load_service("RedTeamService")
    return cls(redteam, tracer, audit)


@pytest.fixture
def gate_service(evaluation_service, redteam_service, model_card_store, tracer, audit):
    """PromotionGateService(evaluation_service, redteam_service, model_card_store, ...)."""
    cls = load_service("PromotionGateService")
    return cls(evaluation_service, redteam_service, model_card_store, tracer, audit)


@pytest.fixture
def prompt_service(prompt_registry, tracer, audit):
    """PromptVersioningService(prompt_registry, tracer, audit)."""
    cls = load_service("PromptVersioningService")
    return cls(prompt_registry, tracer, audit)


@pytest.fixture
def model_card_service(model_card_store, tracer, audit):
    """ModelCardService(model_card_store, tracer, audit)."""
    cls = load_service("ModelCardService")
    return cls(model_card_store, tracer, audit)
