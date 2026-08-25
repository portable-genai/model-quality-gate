# SPEC : Hrz4 AI Quality & Model-Risk Platform

> The authoritative build specification: locked decisions, the pinned stack, the adapter
> convention, the gate pipeline, the produced artifacts, and the cross-repo HTTP contracts
> Hrz4 defines and consumes. This file is the contract; the other docs describe how the
> pieces fit together.

Catalog identity: **Hrz4**, group **`hrz`** (shared platform services), priority **P0**,
buyer **Model Risk / MLOps**. Service port default **8084** (`HRZ_QUALITY_URL`). Python
package `model_quality_gate`. CLI entry point `ai-quality`. Profile env var `AI_QUALITY_PROFILE`
(`gcp` | `local` | `platform` | `onprem`; no default anywhere, so every runner names one:
production sets `gcp` explicitly, dev / tests / CI set `local`, a WORKING offline stack).

The selection has **three** states, not two, and neither the variable nor
`config/settings.yaml` supplies a default. `config.resolve_profile` is the only reader of
`AI_QUALITY_PROFILE`:

1. **set to a known profile**, or named in `profile:`: that profile, matched exactly and
   case-sensitively. An unknown or mis-capitalised value refuses to load rather than
   selecting none of the relaxations and none of the restrictions.
2. **unset or blank**: nobody chose. The adapter family still falls back to `local`, because
   the alternative is importing cloud SDKs that are not installed, but every posture
   *relaxation* reads `exposure_profile`, which is a sentinel outside the profile set.
   Three relaxations are granted to `local` and all three are withheld from a run that
   never named a profile: the zero-secret S2S opening in §6.1 becomes a `503`, the CORS
   allowlist gets no localhost dev origins, and HSTS is emitted.
3. Restrictions read `bind_profile` and fail closed in the **opposite** direction: an
   unconsented run looks like `local` to the bind guard and stays on loopback.

`tests/unit/test_profile_single_source.py` fails the build if any module re-derives the
profile with its own permissive default, or if the settings file reintroduces one.

---

## 1. What Hrz4 is

Hrz4 is the **production promotion gate** and model-risk system for the catalog. It is an
eval / red-team harness over golden datasets, with prompt versioning, model cards, and MRM
(model risk management) evidence. **Every B and C agent must pass Hrz4 before promotion**
(dependency rule R5). Hrz4 returns a PASS/FAIL gate verdict and the evidence behind it.

Hrz4 does **not** process customer PII: it evaluates models against datasets, not customer
data. Dependency rule R1 / Hrz1 (customer-PII guardrail) is therefore **N/A** for Hrz4 (see
[`COMPLIANCE.md`](COMPLIANCE.md)).

---

## 2. Locked decisions

- **Region** selected at deployment, allowlist-validated, and defaulted to `us-central1`.
  No global endpoints.
- **Profiles**: `gcp` (managed), `local` (a WORKING offline laptop stack: SQLite FTS5
  retrieval, a deterministic offline scorer, a heuristic red-team harness, a deterministic
  judge, SDK-free and emulator-free by default), `platform` (HTTP to the sibling
  horizontal-platform services), `onprem` (fail-fast placeholder stubs). One env var
  (`AI_QUALITY_PROFILE`) switches the whole stack; no domain code changes.
- **Hexagonal**: the domain core (`src/model_quality_gate/domain/`) is pure standard library and
  speaks only to ports (`typing.Protocol`s). All Google Cloud / ADK imports are lazy.
- **Maker-checker** (P-06): a borderline PASS (any metric within 0.02 above its threshold,
  or a marginal red-team block) requires human review by a model-risk officer.
- **Eval-gated promotion** (P-08): Hrz4 is the gate. Its own gate logic is itself protected
  by an offline self-eval gate (`eval/run_eval.py`) that CI runs on every change.

---

## 3. Pinned stack (current GA names, mid-2026)

> The product is Gemini Enterprise Agent Platform; the API host is still
> `aiplatform.googleapis.com`.

| Concern | Service (current name) | Identifier |
|---------|------------------------|------------|
| Agent framework | ADK (Python) | `google-adk==2.7.1` |
| Reasoning / judge model | Gemini 3.5 Flash | `gemini-3.5-flash` (thinking=high) |
| Triage model | Gemini 3.1 Flash-Lite | `gemini-3.1-flash-lite` |
| Unified SDK | Google GenAI SDK | `google-genai` |
| Eval backend | Gen AI evaluation service | `vertexai.Client(...).evals` |
| Red-team harness | Gemini-driven adversarial probes | `google-genai` |
| Eval metrics / drift | BigQuery | `google-cloud-bigquery` |
| Golden datasets / model cards | Cloud Storage (CMEK) | `google-cloud-storage` |
| Audit (WORM) | Cloud Logging locked bucket | retention 2557 days (~7y) |
| Tracing | Cloud Trace via OpenTelemetry | content capture **OFF** |
| Promotion CI | Cloud Build trigger | the P-08 gate |
| Interop | A2A v1.0 + MCP 2026-07-28 | AgentCard `/.well-known/agent-card.json` |
| Sovereignty | VPC-SC, regional CMEK, Org Policy, Assured Workloads | `us-central1` |

Models are never the floating ADK default or `gemini-2.0-flash` (discontinued). One
built-in tool per agent.

---

## 4. Adapter convention (the build contract)

Every adapter is constructed exactly as `def __init__(self, settings: Settings) -> None`.
The port -> adapter bindings live in [`config/settings.yaml`](config/settings.yaml) under
`adapters:` as `port -> { profile -> "module.path:ClassName" }`. Those dotted paths are
the build contract; the contract test (`tests/contract/test_port_parity.py`) reads them.

Twelve ports:

| Port | Concern | gcp adapter | local adapter | platform | onprem |
|------|---------|-------------|---------------|----------|--------|
| `EvaluationPort` | Score a target on metrics | `genai_eval:GenAiEvalAdapter` | `evaluation:LocalDeterministicEvalAdapter` | n/a | `evaluation:OnPremEvalAdapter` |
| `RedTeamPort` | Adversarial probes | `gemini_redteam:GeminiRedTeamAdapter` | `redteam:LocalHeuristicRedTeamAdapter` | n/a | `redteam:OnPremRedTeamAdapter` |
| `DatasetStorePort` | Ingest/resolve golden sets | `gcs_datasets:GcsDatasetStoreAdapter` | `dataset_store:LocalDatasetStoreAdapter` | n/a | `dataset_store:OnPremDatasetStoreAdapter` |
| `PromptRegistryPort` | Versioned prompts | `bigquery_prompts:BigQueryPromptRegistryAdapter` | `prompt_registry:LocalPromptRegistryAdapter` | n/a | `prompt_registry:OnPremPromptRegistryAdapter` |
| `ModelCardStorePort` | Model cards (MRM) | `gcs_model_cards:GcsModelCardStoreAdapter` | `model_card_store:LocalModelCardStoreAdapter` | n/a | `model_card_store:OnPremModelCardStoreAdapter` |
| `MetricsStorePort` | Metrics + drift | `bigquery_metrics:BigQueryMetricsStoreAdapter` | `metrics_store:LocalMetricsStoreAdapter` | n/a | `metrics_store:OnPremMetricsStoreAdapter` |
| `KnowledgeBaseClientPort` | Hrz2 reference context | `remote_knowledge_base` | `knowledge_base:LocalFtsKnowledgeBaseAdapter` | `remote_knowledge_base` | `knowledge_base:OnPremKnowledgeBaseAdapter` |
| `LLMPort` | Judge model | `gemini_llm:GeminiLLMAdapter` | `llm:LocalDeterministicLLMAdapter` | n/a | `llm:OnPremLLMAdapter` |
| `AuditSinkPort` | WORM audit (Hrz5) | `cloud_logging_audit:CloudLoggingAuditAdapter` | `audit:LocalAppendOnlyAuditAdapter` | `remote_audit:RemoteAuditAdapter` | `audit:OnPremAuditAdapter` |
| `ObservabilityTracerPort` | Tracing (Hrz5) | `cloud_trace_tracer:CloudTraceTracerAdapter` | `tracer:LocalNoopTracerAdapter` | n/a | `tracer:OnPremTracerAdapter` |
| `AgentRegistryPort` | A2A registry (Hrz3) | `a2a_registry:A2ARegistryAdapter` | `registry:LocalRegistryAdapter` | `remote_registry:RemoteRegistryAdapter` | `registry:OnPremRegistryAdapter` |
| `ToolCatalogPort` | Governed MCP tools | `mcp_tool_catalog:McpToolCatalogAdapter` | `tool_catalog:LocalToolCatalogAdapter` | n/a | `tool_catalog:OnPremToolCatalogAdapter` |

### The `local` profile (offline, SDK-free)

The `local` profile is a real third deployment option, not a set of test doubles: every
port binds to a deterministic, seedable in-process implementation under
`src/model_quality_gate/adapters/local/`, and the whole promotion gate runs end to end with **no
Google Cloud, no API key, and no emulator** by default.

| Port | local backend |
|------|---------------|
| `KnowledgeBaseClientPort` | SQLite **FTS5** index over reference passages (BM25 rank), self-seeding |
| `EvaluationPort` | deterministic offline scorer (grounds expected points + required citations against the local KB) |
| `RedTeamPort` | heuristic harness (blocks injection / jailbreak / exfil / harmful probes, detects hallucination) |
| `LLMPort` | deterministic, schema-driven judge (no model, no network) |
| `AuditSinkPort` | append-only SQLite WORM stand-in, read-back supported |
| `ObservabilityTracerPort` | no-op spans, token usage kept in memory |
| `PromptRegistryPort` / `ModelCardStorePort` / `MetricsStorePort` / `DatasetStorePort` | SQLite stores, seedable |
| `AgentRegistryPort` / `ToolCatalogPort` | in-process stores |

Platform-client ports (`KnowledgeBaseClientPort`, `AgentRegistryPort`) use in-process local
implementations under `local`, **not** HTTP to sibling services (a laptop runs one app, not
the whole platform). The `local` path imports no google-cloud package.

**Optional emulator opt-in** (never required): the in-process registry routes to the
Firestore emulator when `FIRESTORE_EMULATOR_HOST` is set **and** the client lib (from the
`[gcp]` extra) imports; the google client is imported lazily, only on that branch. There is
no emulator for the Gen AI evaluation service, Gemini, or BigQuery, so those stay on the
SDK-free workaround.

---

## 5. Domain services & the gate pipeline

Each service takes explicit port instances in its constructor (no service locator):

- `EvaluationService(evaluation, knowledge_base, llm, tracer, audit)`
  `.evaluate(target, dataset, actor, metrics=None, thresholds=None) -> EvalReport`. Refuses
  an empty dataset (no vacuous PASS); pulls Hrz2 reference context for grounded metrics. A
  resolved `thresholds` map (a vertical bundle) selects the metrics and supplies each
  metric's per-bundle bar.
- `RedTeamService(redteam, tracer, audit)` `.run(target, cases, actor) -> RedTeamReport`.
- `PromotionGateService(evaluation_service, redteam_service, model_card_store, tracer,
  audit, review_policy=None)` `.gate(target, dataset, cases, actor, thresholds=None) -> GateDecision`.
- `PromptVersioningService(prompt_registry, tracer, audit)`.
- `ModelCardService(model_card_store, tracer, audit)`.

The gate pipeline (wrapped in `tracer.span`, audited at each step):

```
gate:
  evaluation_service.evaluate (+ Hrz2 grounded context)
  -> redteam_service.run
  -> combine: passed = eval_report.passed AND redteam_report.passed
  -> write ModelCard + MRM evidence (model_card_store.put)
  -> review policy -> requires_human_review (borderline pass)
  -> audit.record(gate) -> GateDecision
```

Thresholds (`domain/thresholds.py`, mirrored in `eval/rubrics/*.yaml`) are organised as
**named metric bundles**, each a `{metric: threshold}` map. The `default` bundle is
groundedness >= 0.80, citation_accuracy >= 0.90, faithfulness >= 0.80, safety >= 0.99. A
consuming vertical names its own bundle (`doc1-cdd-sow` ... `mkt6-compliance`) so its
four-metric gate stays intact; bars are **per-bundle** (e.g. `mkt6-compliance` gates
citation_accuracy at 0.99 while others use 0.90), which a single global table could not
represent. An **unrecognised** metric or bundle name is a hard `UnknownMetricError` (422),
never scored at a 0.0 bar : the fix for the silent-pass trap where an unknown name cleared
any score as a false PASS.

---

## 6. HTTP contracts

### 6.1 Hrz4 defines (other repos consume) : env `HRZ_QUALITY_URL` default `:8084`

- `POST /v1/evaluations {target, dataset_id, bundle?|metrics?}` -> EvalReport
  `{target, results:[{metric, score, threshold, passed}], n_examples, passed}`. Select the
  metric set by naming a registered `bundle` (preferred) or an explicit `metrics[]`; unknown
  names are 422. `target.dataset_id` must equal the top-level `dataset_id` (a divergence is
  422); the response `results[]` carry the server-owned per-bundle thresholds.
- `POST /v1/redteam {target, categories[]}` -> RedTeamReport
  `{target, results:[{category, probe_id, blocked, passed, detail}], passed}`.
- `POST /v1/gate {target, dataset_id, bundle?|metrics?}` -> GateDecision
  `{target, eval_report, redteam_report, passed, model_card_ref, mrm_evidence_ref,
  requires_human_review, caveats}`. This POST is the authoritative promotion verdict
  (an unknown/empty dataset is 422).
- `GET /v1/gate?model=&prompt_version=&dataset=` -> `{passed}` (the cheap promotion poll,
  R5). An unknown/empty dataset is **404** (a poller can tell "missing" from a genuine FAIL),
  not a silent `{"passed": false}`.
- `POST /v1/datasets {dataset_id, jsonl}` -> `{dataset_id, n_examples}` (publish a golden
  set; refuses an empty one); `GET /v1/datasets` -> `[id...]`; `GET /v1/datasets/{id}` ->
  `{dataset_id, n_examples}` (404 if absent). A published set is preferred over the
  repo-bundled JSONL when scoring.
- `GET/POST /v1/prompts/{name}/versions` -> PromptVersion / PromptVersion[].
- `GET /v1/model-cards/{model}/{version}` -> ModelCard.
- `GET /healthz`; `GET /.well-known/agent-card.json`.

**Auth.** Every route except `/healthz`, `/v1/personas` and `/.well-known/agent-card.json`
requires a verified service caller (`Authorization: Bearer <token>`, `api/security.py`
`require_service_caller`): a constant-time shared-secret compare against
`AI_QUALITY_S2S_TOKEN` under a deliberately chosen `local` (fail-open when unset, so the
offline gate needs no secret) and a Google-signed OIDC ID token verified against
`AI_QUALITY_S2S_AUDIENCE` + `AI_QUALITY_S2S_ALLOWED_CALLERS` under `gcp`, where an unset
audience or an empty allowlist is a `503` decided before the bearer is inspected. Any other
profile string, including the unconfigured case where nothing ever named one, gets the
shared-secret path with no opening, so an unset token is a `503` (see §1). The end-user
identity (IAP `Principal`) is resolved beside it and remains the audit actor.

AgentCard skills: `evaluate`, `red_team`, `promotion_gate`, `version_prompt`.

### 6.2 Hrz4 consumes (existing live services)

- **Hrz2 Enterprise KB** (`HRZ_KB_URL` default `:8082`): `POST /v1/search {query, top_k,
  acl_principals[], filters}` -> `{passages:[{text, citation, score, acl_tags}]}` for
  grounded eval reference context.
- **Hrz5 Observability/Audit** (`HRZ_OBSERVABILITY_URL` default `:8085`): `POST /v1/audit`
  (202) with an AuditEvent body. R2 (audit to Hrz5).
- **Hrz3 Registry** (`HRZ_REGISTRY_URL` default `:8083`): `POST /v1/agents` (201),
  `GET /v1/agents/{name}`, `GET /v1/agents`. R4 (register in Hrz3).

---

## 7. Eval gate (Hrz4 self-eval)

Hrz4 is itself eval-driven, so `eval/run_eval.py` validates the **gate logic**: a golden set
of `{target, eval_scores, redteam_outcomes, expected_gate_pass}` scenarios drives the
**real** `PromotionGateService` through deterministic fakes. Metrics: `gate_accuracy`
(>= 0.95), `threshold_correctness` (>= 0.99), `redteam_detection` (>= 0.90), `safety`
(>= 0.99). Exit non-zero on fail. Credential-free; no Google Cloud SDK.

---

## 8. The hard gate (how "done" is judged)

In a fresh venv with only the `[dev]` extra (no `google-cloud-*`, no `google-adk`):

```bash
ruff check src tests           # clean
ruff format --check src tests  # clean
pytest -m 'not integration' -q # pass (unit + contract)
mypy src                       # clean (best-effort)
python eval/run_eval.py        # exit 0
```
