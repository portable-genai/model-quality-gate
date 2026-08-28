# Compliance mapping : Hrz4 AI Quality & Model-Risk Platform

This document maps every **General Principle** (P-01..P-12) and **dependency rule**
(R1..R6) to a concrete control, file, or resource in **this** repo. Where a principle does
not apply to Hrz4, it is marked **N/A** with the reason, honestly, rather than claimed.

Hrz4 is the catalog's **production promotion gate** (rule R5) and the concrete home of
**P-08** (eval-gated promotion) and model-risk governance. It evaluates models against
datasets and does **not** process customer personal data, which is why the customer-PII
principles and rule R1 are N/A here.

---

## General Principles (P-01..P-12)

| # | Principle | Hrz4 status | Where it lives |
|---|-----------|-----------|----------------|
| **P-01** | Managed-first, minimal surface | Applies | `infra/terraform/apis.tf` enables only the services the pinned stack uses; `vpc_sc.tf` restricts the perimeter to those services. |
| **P-02** | No vendor lock-in (ports & adapters) | **Core** | The domain ([`src/model_quality_gate/domain/`](src/model_quality_gate/domain/)) depends only on `typing.Protocol` ports; `config/settings.yaml` binds them; one env var (`AI_QUALITY_PROFILE`) swaps the whole stack across `gcp` / `local` / `platform` / `onprem`. The `local` family ([`src/model_quality_gate/adapters/local/`](src/model_quality_gate/adapters/local/)) proves the domain runs **entirely off-cloud** (the gate runs end to end with no google-cloud package), and the `onprem` family proves interface parity; both are exercised by [`tests/contract/test_port_parity.py`](tests/contract/test_port_parity.py). |
| **P-03** | Data residency / in-country | Applies | Region pinned `asia-southeast1` everywhere; Terraform validates it and fails fast (`variables.tf`); regional CMEK (`kms.tf`); VPC-SC perimeter (`vpc_sc.tf`); BigQuery + GCS pinned in-region. |
| **P-04** | Minimise data to the model | Partial / context-specific | Hrz4 evaluates models against synthetic golden datasets and adversarial probes; **no customer data** is sent to a model. Only the probe text and golden inputs reach the judge model. The red-team adapter sends only synthetic probes. |
| **P-05** | Private-only data plane | Applies | GCS buckets enforce uniform access + public-access-prevention (`cloud_storage.tf`); BigQuery and the eval service sit inside the VPC-SC perimeter. |
| **P-06** | Human-in-the-loop (maker-checker) | **Supported** | `GateReviewPolicy` ([`domain/hitl.py`](src/model_quality_gate/domain/hitl.py)) flags a borderline PASS (any metric within 0.02 above threshold, or a marginal red-team block) for a model-risk officer's sign-off; such verdicts audit as `ESCALATED`. |
| **P-07** | Audited everything / model-risk evidence | **Core** | Every gate / eval / red-team / prompt / model-card action writes an immutable `AuditEvent` to the locked WORM bucket (`cloud_logging_audit.py`, `logging_worm.tf`); each gate writes a `ModelCard` + MRM evidence pointer (`gate_service.py`, `gcs_model_cards.py`); prompt versions are checksummed change-control records (`prompt_service.py`, `bigquery_prompts.py`). |
| **P-08** | Eval-gated promotion | **This IS the gate** | `PromotionGateService` ([`domain/gate_service.py`](src/model_quality_gate/domain/gate_service.py)) is the promotion gate; thresholds in `domain/thresholds.py` + `eval/rubrics/*.yaml`; the offline self-eval gate (`eval/run_eval.py`) protects the gate logic; Cloud Build runs it in CI (`cloudbuild.tf`, `.github/workflows/eval-gate.yaml`). |
| **P-09** | CMEK does not cascade | Applies | One regional key ring; every service that encrypts (BigQuery, Cloud Storage, Vertex/Agent Platform, Logging) gets its own explicit key binding in `kms.tf`. |
| **P-10** | Cost / FinOps observability | Applies | `ObservabilityTracerPort.record_token_usage` emits token counts as span attributes (`cloud_trace_tracer.py`); BigQuery retains per-run eval metrics for cost/quality trend analysis. |
| **P-11** | Reproducibility / determinism | Applies | The judge runs at `temperature=0.0`; prompt versions are checksummed; the self-eval gate is fully deterministic so a gate-logic regression is caught in CI; the `local` profile's scorer, judge and red-team harness are deterministic and seedable, so an offline gate run reproduces exactly. |
| **P-12** | Exit / portability | **Core** | The `local` adapter family is a WORKING off-cloud proof that the domain runs with no managed dependency, and the `onprem` adapter family ([`src/model_quality_gate/adapters/onprem/`](src/model_quality_gate/adapters/onprem/)) is a complete set of placeholder stubs that satisfy every Protocol and **fail fast** (the CLI exits 2 with the migration message); [`docs/onprem-migration.md`](docs/onprem-migration.md) is the documented migration checklist (Google Distributed Cloud target). |

---

## Dependency rules (R1..R6)

| # | Rule | Hrz4 status | Where it lives |
|---|------|-----------|----------------|
| **R1** | Customer-PII guardrail via Hrz1 | **N/A** | Hrz4 evaluates models against datasets, not customer data, so there is no customer-PII path to guard. No Hrz1 dependency. (If a future golden dataset ever carried real customer data, Hrz1 redaction would be added on ingestion : not in scope today.) |
| **R2** | Audit to Hrz5 | Applies | `AuditSinkPort` -> `RemoteAuditAdapter` posts every `AuditEvent` to `agent-observability` `/v1/audit` (platform profile); the `gcp` profile writes Cloud Logging WORM directly. |
| **R3** | Tracing to Hrz5 | Applies | `ObservabilityTracerPort` -> Cloud Trace via OpenTelemetry (`cloud_trace_tracer.py`), content capture OFF. |
| **R4** | Register in Hrz3 | Applies | `AgentRegistryPort` -> `RemoteRegistryAdapter` registers the Hrz4 AgentCard in `agent-registry`; the card is also served at `/.well-known/agent-card.json`. |
| **R5** | Pass the Hrz4 eval gate before promotion | **This IS Hrz4** | Hrz4 *is* the gate the rest of the catalog must pass. The `GET /v1/gate?model=...` endpoint is the cheap promotion poll sibling pipelines call (404 on an unknown/empty dataset, so a poller can tell "missing" from FAIL); the gate logic is `PromotionGateService`. A caller selects its per-vertical metric bundle by name; an unrecognised metric/bundle is a 422, never a silent PASS. Every non-health route requires a verified **service caller** (`api/security.py` `require_service_caller`: shared-secret in `local`, OIDC ID token + allowlist in `gcp`), so the promotion gate authenticates the calling service, not just the end user. |
| **R6** | Consume the Hrz2 Enterprise KB for grounded knowledge | Applies | `KnowledgeBaseClientPort` -> `RemoteKnowledgeBaseAdapter` pulls reference context from `enterprise-knowledge-base` `/v1/search` for grounded evaluation. |

---

## Honest gaps and scope notes

- **P-04 is context-specific, not absolute.** Hrz4 does not handle customer PII, so the
  "minimise PII to the model" control that a customer-facing assistant needs is N/A in its
  strict form. The analogous control here is that only synthetic golden inputs and
  adversarial probes reach a model.
- **R1 / Hrz1 is N/A by design.** Marking it N/A is deliberate: claiming an Hrz1 guardrail
  dependency Hrz4 does not have would be misleading. Should Hrz4 ever evaluate over a dataset
  derived from production traffic, Hrz1 redaction must be added at dataset-ingestion time.
- **Terraform is not applied here.** The infra encodes the residency, CMEK, WORM and
  least-privilege controls above, but a real deployment requires your own security and
  model-risk sign-off (the WORM lock is irreversible).

---

## Regulator crosswalk (ADOPTER-OWNED)

**Ownership.** This appendix is owned by the ADOPTING institution, not by this repository.
Upstream ships it as a filled-in template for one home regulator (MAS, Singapore) so the
shape is unambiguous; a fork replaces the rows with its own regulator and keeps the file.
Merges from upstream never overwrite this section (see
[`docs/ADOPTING.md`](docs/ADOPTING.md), adopter-owned files). Nothing here is legal advice
or a regulatory filing: it maps *what this platform does* to the obligations an adopter
must evidence, so a model-risk reviewer can start from concrete artefacts rather than prose.

Columns: the regulator's obligation, the internal principle it lands on, the control that
implements it here, and the artefact a reviewer can open.

| Regulator reference (MAS, Singapore) | Obligation in scope for a model-risk gate | Internal principle | Control here | Evidence |
|---|---|---|---|---|
| MAS Guidelines on Risk Management Practices, model risk | Independent validation before a model is used in production | P-08, R5 | `PromotionGateService` returns a PASS/FAIL verdict from eval AND red-team; the verdict is pure code and the LLM only scores metrics | `src/model_quality_gate/domain/gate_service.py`, `tests/unit/test_redteam_and_gate.py` |
| MAS Guidelines on Risk Management Practices, model risk | Documented, approved thresholds owned by the risk function | P-08 | Promotion bars and the maker-checker band are a `policy:` settings section; defaults equal the reference constants and an override changes the verdict | `config/settings.yaml`, `src/model_quality_gate/domain/policy.py`, `tests/unit/test_promotion_policy.py` |
| MAS FEAT principles (fairness, ethics, accountability, transparency) | An accountable human signs off consequential model decisions | P-06 | A borderline PASS or a marginal red-team block sets `requires_human_review` and audits as `ESCALATED`; escalation only raises the bar | `src/model_quality_gate/domain/hitl.py`, `tests/unit/test_policies.py` |
| MAS TRM Guidelines s.7 (access control, least privilege) | Restrict system access to authorised parties, verified server-side | P-05 | `require_service_caller` on every non-health route plus a server-resolved `Principal`; request schemas carry no client actor | `src/model_quality_gate/api/security.py`, `tests/unit/test_api_s2s_auth.py` |
| MAS TRM Guidelines s.11 (cryptography and key management) | Protect data at rest with keys under the institution's control | P-09 | One regional CMEK key ring, bound explicitly per service because CMEK does not cascade | `infra/terraform/kms.tf`, `tests/unit/test_residency_posture.py::test_cmek_is_bound_per_service_because_it_does_not_cascade` |
| MAS Outsourcing / cloud advisory (data residency) | Keep regulated records within approved jurisdictions | P-03 | One residency allowlist enforced three times: at `terraform plan`, by Org Policy `gcp.resourceLocations`, and at application load | `infra/terraform/org_policy.tf`, `src/model_quality_gate/config.py`, `tests/unit/test_residency_posture.py` |
| MAS Outsourcing / cloud advisory (exit and reversibility) | Demonstrate an exit path from the service provider | P-12 | Three profiles behind one port set; `local` runs the whole gate off cloud, `onprem` is the fail-fast exit target; the portability claim is executable | `docs/onprem-migration.md`, `scripts/portability_demo.py` |
| MAS Notice 644 / TRM incident reporting | Retain records needed to reconstruct a decision, tamper-evident | P-07 | Hash-chained append-only audit with per-line verification on export; the managed profile sinks to a locked WORM bucket | `src/model_quality_gate/adapters/local/audit.py`, `infra/terraform/logging_worm.tf`, `tests/unit/test_audit_chain.py` |
| MAS TRM Guidelines s.8 (systems acquisition and development) | Reproducible builds and controlled dependencies | P-11 | Compiled lockfiles per extra, digest-pinned base image, SHA-pinned Actions, `pip-audit` as a hard gate | `requirements-dev.lock`, `requirements-gcp.lock`, `.github/workflows/ci.yaml` |

**What this crosswalk does not claim.** It does not assert compliance. Live enforcement
evidence (an Org Policy actually applied to a named project, a VPC Service Controls
perimeter promoted out of dry run, a locked retention policy on a real bucket, IdP
registrations) exists only after the adopter deploys; until then these rows point at
posture-as-code, which is the input to that evidence and not a substitute for it.
