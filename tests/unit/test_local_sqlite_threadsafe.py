"""Concurrency regression: the local SQLite adapters are safe across worker threads.

Under ``local serve`` the FastAPI container is process-wide (``api.deps.get_container`` is
``@lru_cache``d, so one adapter instance with one ``sqlite3`` connection) while the sync
``def`` endpoints run in Starlette's anyio worker threadpool. A request handled on a worker
thread therefore calls ``record()`` / ``put()`` / ``retrieve()`` on a connection opened by a
*different* thread. Without ``check_same_thread=False`` plus a serialising lock, sqlite3
raises ``ProgrammingError: SQLite objects created in a thread can only be used in that same
thread``, dropping the WORM audit event and 500-ing the request under concurrency.

These tests construct each SQLite-backed local adapter **once** and then drive interleaved
writes and reads from many threads via a ``ThreadPoolExecutor``, asserting no exception is
raised and the final row counts are exact. They fail before the ``check_same_thread=False``
+ lock fix (with the cross-thread ``ProgrammingError``) and pass after it.
"""

from __future__ import annotations

import concurrent.futures

from model_quality_gate.adapters.local.audit import LocalAppendOnlyAuditAdapter
from model_quality_gate.adapters.local.knowledge_base import LocalFtsKnowledgeBaseAdapter
from model_quality_gate.adapters.local.metrics_store import LocalMetricsStoreAdapter
from model_quality_gate.adapters.local.model_card_store import LocalModelCardStoreAdapter
from model_quality_gate.adapters.local.prompt_registry import LocalPromptRegistryAdapter
from model_quality_gate.config import LocalSettings, Settings
from model_quality_gate.domain.models import (
    AuditEvent,
    Citation,
    Decision,
    EvalMetricResult,
    EvalReport,
    EvalTarget,
    ModelCard,
    PromptVersion,
)

_THREADS = 8
_PER_THREAD = 25
_TOTAL = _THREADS * _PER_THREAD


def _settings() -> Settings:
    # A single shared in-memory connection per adapter (in-memory DBs are per-connection,
    # so the one connection opened in __init__ is the one all worker threads must reach).
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


def _drive(fn) -> list:
    """Run ``fn(i)`` for i in range(_TOTAL) across a thread pool, raising the first
    exception any worker hit (so a cross-thread sqlite3 error fails the test)."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=_THREADS) as pool:
        futures = [pool.submit(fn, i) for i in range(_TOTAL)]
        return [f.result() for f in concurrent.futures.as_completed(futures)]


def test_audit_adapter_is_thread_safe() -> None:
    adapter = LocalAppendOnlyAuditAdapter(_settings())

    def work(i: int) -> int:
        adapter.record(
            AuditEvent(
                action="gate",
                actor=f"svc-{i}",
                decision=Decision.ALLOWED,
                redacted_prompt="gate pass",
            )
        )
        # Interleave a read on the same connection from the worker thread too.
        return len(adapter.read_all())

    _drive(work)

    assert len(adapter.read_all()) == _TOTAL


def test_knowledge_base_adapter_is_thread_safe() -> None:
    adapter = LocalFtsKnowledgeBaseAdapter(_settings())
    # Start from a known-empty index so the final count is deterministic.
    adapter.seed([])

    def citation(i: int) -> Citation:
        return Citation(
            source_id=f"ref-{i}",
            title=f"Notice {i}",
            url=f"https://example.test/{i}",
            page=1,
            snippet=f"capital adequacy buffer requirement clause {i}",
            score=0.5,
        )

    def work(i: int) -> int:
        # Mix writes (add) and reads (retrieve) on the shared connection.
        adapter.add([citation(i)])
        return len(adapter.retrieve("capital adequacy requirement", top_k=5))

    results = _drive(work)

    # Every retrieve ran without a cross-thread error and returned ranked rows.
    assert all(r >= 0 for r in results)
    assert any(r > 0 for r in results)


def test_metrics_store_adapter_is_thread_safe() -> None:
    adapter = LocalMetricsStoreAdapter(_settings())

    def work(i: int) -> object:
        report = EvalReport(
            target=EvalTarget(model="gemini-3.7-flash", prompt_version=f"v{i}", dataset_id="ds"),
            results=(
                EvalMetricResult(metric="groundedness", score=0.9, threshold=0.8, passed=True),
            ),
            n_examples=1,
        )
        adapter.record(report)
        # Interleave a drift read on the same connection from the worker thread.
        return adapter.drift("gemini-3.7-flash")

    _drive(work)

    # One metric ("groundedness") recorded _TOTAL times for the model.
    signals = adapter.drift("gemini-3.7-flash")
    assert len(signals) == 1
    assert signals[0].metric == "groundedness"


def test_model_card_store_adapter_is_thread_safe() -> None:
    adapter = LocalModelCardStoreAdapter(_settings())

    def work(i: int) -> object:
        card = ModelCard(
            model="gemini-3.7-flash",
            version=f"v{i}",
            intended_use="grounded compliance QA",
            metrics={"groundedness": 0.9},
        )
        adapter.put(card)
        return adapter.get(card.model, card.version)

    results = _drive(work)

    # Every put/get round-tripped without a cross-thread error.
    assert all(r is not None for r in results)
    assert adapter.get("gemini-3.7-flash", "v0") is not None


def test_prompt_registry_adapter_is_thread_safe() -> None:
    adapter = LocalPromptRegistryAdapter(_settings())

    def work(i: int) -> object:
        version = PromptVersion(
            name="compliance-qa",
            version=f"v{i}",
            template=f"answer grounded in citations {i}",
            checksum=f"sha-{i}",
        )
        adapter.put(version)
        # Interleave reads (get + list) on the shared connection.
        adapter.list("compliance-qa")
        return adapter.get(version.name, version.version)

    _drive(work)

    assert len(adapter.list("compliance-qa")) == _TOTAL
