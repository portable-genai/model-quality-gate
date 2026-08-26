# Runbook : Hrz4 AI Quality & Model-Risk Platform

Operational notes for deploying and running Hrz4 in `us-central1`. This is a reference
build: adapt to your own change-management and sign-off processes before production use.

## Deploy (gcp profile)

1. **Provision infra.** Review and apply the Terraform in
   [`infra/terraform/`](../infra/terraform/):
   ```bash
   cd infra/terraform
   cp terraform.tfvars.example terraform.tfvars   # edit project_id, org_id, ...
   terraform init -input=false
   terraform plan                                  # review EVERY resource
   # terraform apply                               # only with security + model-risk sign-off
   ```
   The plan fails fast if `region` is not in `allowed_regions` (P-03).

2. **Wire settings.** Export the Terraform outputs into the runtime environment (or paste
   into `config/settings.yaml`):
   ```bash
   export AI_QUALITY_KMS_KEY="$(terraform output -raw kms_key)"
   export GOOGLE_CLOUD_PROJECT="$(terraform output -raw project_id)"
   ```

3. **Build and run the API.**
   ```bash
   docker build -t ai-quality:0.1.0 .
   # deploy to Cloud Run / Agent Runtime; the image listens on :8084 and exposes /healthz
   ```

4. **Deploy the agent (optional).** Wrap `build_root_agent(Settings.load())` with the Agent
   Platform SDK and record the `reasoningEngine` resource name in
   `settings.agent_engine.resource_name`.

## The promotion gate (the daily job)

Hrz4 is the gate the rest of the catalog calls. A sibling promotion pipeline polls:

```bash
curl "https://<a4-host>/v1/gate?model=gemini-3.5-flash&prompt_version=v3&dataset=compliance-qa-golden"
# -> {"passed": true}
```

A full gate with evidence. The audit actor is the server-verified identity (from the
IAP-verified assertion behind Cloud IAP, or a seeded persona via `X-Dev-Persona` in local
mode), never a request-body field (docs/embedding-and-identity.md):

```bash
curl -X POST https://<a4-host>/v1/gate \
  -H 'content-type: application/json' \
  -d '{"target":{"model":"gemini-3.5-flash","prompt_version":"v3","dataset_id":"compliance-qa-golden"},"dataset_id":"compliance-qa-golden"}'
```

A `requires_human_review: true` verdict means the PASS was borderline: route it to a
model-risk officer before promoting (maker-checker, P-06).

## Region fail-fast

Every adapter targets the configured region (default `us-central1`). If the Gen AI
evaluation service or another required service is unavailable there, the relevant call fails rather than silently
falling back to a global endpoint (which would break residency).

## Key rotation

The CMEK crypto key (`kms.tf`) rotates every 90 days automatically. Rotation is transparent
to the app: BigQuery, Cloud Storage and the log bucket re-encrypt with the new primary key
version. Do **not** destroy the key (`prevent_destroy` is set): it would strand all
CMEK-encrypted data.

## Retention (irreversible)

The WORM audit bucket (`logging_worm.tf`) is **locked** with ~7-year retention. This cannot
be undone, not even with project-owner rights. Confirm `retention_days` before the first
apply.

## Kill switch

To stop serving gate verdicts without losing evidence: scale the API to zero (Cloud Run) or
undeploy the Agent Runtime. The BigQuery metrics, model cards, and the WORM audit log are
retained independently, so historical evidence survives a service outage.

## Drift monitoring

Every evaluation is recorded, and `MetricsStorePort.drift(model)` compares each metric's
latest score against its baseline. `domain/drift.py` bands the movement (`stable` under
0.05, `warning` from 0.05, `alert` from 0.10 in absolute magnitude) and decides what the
reading owes a human. Both the SQLite and BigQuery stores band through that one function,
so a re-tuned band cannot mean one thing on a laptop and another in production.

Read it on either surface. No dashboard has to be built first:

```bash
curl "https://<a4-host>/v1/drift/gemini-3.5-flash"
# -> {"model":"...","status":"alert","requires_re_gate":true,"requires_human_review":true,
#     "escalating_metrics":["groundedness"],"signals":[...],"reasons":[...]}
```

```bash
ai-quality drift gemini-3.5-flash   # exits 1 when a re-gate is owed, 0 otherwise
```

What the statuses require, on a graded ladder:

| Status | Requires |
|---|---|
| `stable` | nothing |
| `warning` | a model-risk review |
| `alert` | a review **and** a re-gate before the model's last verdict may still be relied on |
| `unmeasured` | a review and a re-gate. Nothing is recorded for the model, and an absent measurement is not a stable one |
| `unrecognised` | a review and a re-gate. A signal carried a status this policy does not know, and an unknown band is never read as the calm one |

**The escalation is a requirement, not an action.** `GET /v1/drift/{model}` and
`ai-quality drift` hold no gate service: neither promotes, demotes, nor re-runs the gate,
and the CLI's non-zero exit is a signal for your monitor to page on. Satisfying the
requirement means a person re-running `POST /v1/gate` (P-06, maker-checker). Every read is
written to the immutable audit log as a `drift` event, `ESCALATED` when a human is owed
something, so a raised finding is provable after the fact.

### What is NOT here

This is the offline half of online quality measurement, and the other half is absent
rather than stubbed:

- **No live-traffic sampler.** Nothing writes production inference outcomes into the
  metrics table. The rows come from evaluation runs against golden datasets, so what
  `drift` measures today is eval-over-time, not live-traffic quality. Sampling production
  traffic is yours to build, against `MetricsStorePort.record`.
- **No scheduled re-scorer.** Nothing polls this route, and nothing acts on a
  `requires_re_gate` on its own. Wire the route or the CLI into your own scheduler and
  alerting, deliberately, so that the thing which pages someone is a thing you chose.
