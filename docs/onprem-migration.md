# On-prem migration checklist (exit / portability, P-12)

`model-quality-gate`'s exit story is concrete, not aspirational. Switching from the managed GCP stack to an
on-premise stack (the **Google Distributed Cloud** target) is a one-line profile change,
`AI_QUALITY_PROFILE=onprem`, after which every port is bound to a placeholder adapter under
[`src/model_quality_gate/adapters/onprem/`](../src/model_quality_gate/adapters/onprem/). The domain core
does not change at all : that is the point of the hexagon (P-02).

## What the on-prem profile gives you today

- Every one of the 13 ports has an `onprem` binding in
  [`config/settings.yaml`](../config/settings.yaml).
- Each placeholder **constructs cleanly with no Google Cloud SDK installed** and
  **structurally satisfies the same Protocol** as its managed counterpart. The contract
  test ([`tests/contract/test_port_parity.py`](../tests/contract/test_port_parity.py))
  proves this on every CI run.
- Most stubs **raise `NotImplementedError`** with a message naming the migration target, so
  a half-migrated deployment fails loudly rather than silently doing nothing. The exceptions
  are the tracer (a no-op is safe: tracing is non-essential to correctness).

## Why most stubs raise rather than no-op

For a model-risk gate, a silent default is dangerous:

- **Evaluation / red-team** stubs raise : an unimplemented evaluator must never declare a
  model safe without actually evaluating it (no vacuous PASS).
- **Audit** raises : an unimplemented audit sink must never drop a gate record.
- **Prompt registry / model-card store / metrics store** raise : MRM evidence must not be
  silently lost.
- **Knowledge base** raises : empty reference context would make grounded eval vacuous.
- **Tracer** is a safe no-op : tracing absence does not affect gate correctness.

## Migration steps

For each port, replace the placeholder body with a real on-premise implementation, keeping
the exact Protocol signature. The domain, services, API, CLI, and tests are untouched.

1. **`EvaluationPort`** : implement `score(target, dataset, metrics)` against your
   on-premise evaluation backend (an internal LLM-judge service or a metrics library).
2. **`RedTeamPort`** : implement `run(target, cases)` against your on-premise model endpoint
   plus an assessment step.
3. **`PromptRegistryPort` / `ModelCardStorePort` / `MetricsStorePort`** : implement against
   your on-premise database / object store (the same checksum and schema discipline).
4. **`KnowledgeBaseClientPort`** : implement `retrieve(query, top_k)` against your internal
   enterprise search.
5. **`LLMPort`** : implement `generate` / `classify` against your on-premise model endpoint.
6. **`AuditSinkPort`** : implement `record(event)` against your on-premise immutable (WORM)
   audit store.
7. **`AgentRegistryPort` / `ToolCatalogPort`** : implement against your on-premise registry
   and tool catalog.

## Verifying the migration

After implementing a stub, the contract test still asserts Protocol parity; add an
integration test (marked `@pytest.mark.integration`) that exercises the real backend. The
**self-eval gate** (`eval/run_eval.py`) is backend-agnostic : it validates the gate logic,
which never changes, so it keeps protecting you throughout the migration.

```bash
AI_QUALITY_PROFILE=onprem pytest -m 'not integration' -q   # parity still holds
python eval/run_eval.py                                    # gate logic still correct
```
