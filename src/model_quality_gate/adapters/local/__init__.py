"""Local deployment profile adapters : a WORKING, offline laptop stack.

The ``local`` profile is the third deployment option alongside ``gcp`` (managed Google
Cloud services) and ``onprem`` (fail-fast Google Distributed Cloud migration
placeholders). Unlike ``onprem``, every adapter here is a *real, deterministic*
implementation that runs the whole A4 promotion gate end to end with **no Google Cloud,
no API key, and no running emulators by default**:

* Knowledge base (grounded reference retrieval) -> a ``sqlite3`` **FTS5** index over the
  reference passages (BM25 rank).
* Evaluation (the A4 scoring backend) -> a deterministic, schema-aware scorer that grades
  each golden example against its reference context offline.
* Red-team -> a heuristic harness that blocks prompt-injection / jailbreak / exfiltration
  probes and detects hallucination probes.
* LLM judge -> a deterministic, schema-driven generator (no model, no network).
* Audit -> an append-only local store (SQLite or JSONL), read-back supported.
* Tracer -> no-op spans.
* Prompt registry / model-card store / metrics store -> SQLite stores, seedable.
* Registry / tool catalog -> in-process stores.

Everything is **seedable** so the test suite stays deterministic, and the default code
path imports **no google-cloud package at module top level**. Optional higher-fidelity
local runs route to Google's official emulators when the standard ``*_EMULATOR_HOST`` env
vars are set (the google client is imported lazily, only on that branch); see
:mod:`model_quality_gate.adapters.local._emulator`.
"""
