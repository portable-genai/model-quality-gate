# Demo guide: Hrz4 AI Quality & Model-Risk Platform

Step-by-step scripts for demoing Hrz4 two ways:

- **Demo A: the promotion gate, offline** (the headline flow): a candidate target
  (a model + prompt version + golden dataset) is put through the production-promotion
  gate. The system runs a deterministic evaluation, runs the five-family red-team battery,
  combines them into a PASS/FAIL verdict, and seals a model card as MRM evidence. Runs
  **fully offline** (no cloud, no API key) on the deterministic `local` stack.
- **Demo B: the same gate on the managed GCP stack**: the identical contract running
  against the real Gen AI evaluation service, Gemini judge, BigQuery, Cloud Storage (CMEK)
  and the WORM log bucket in `asia-southeast1`, exposed over REST and the Next.js console.

> The golden datasets and red-team probes are **fictional / synthetic**. Do not gate a
> model against live regulated workloads without your own legal, security and model-risk
> sign-off.

---

## 0. Prerequisites

| Need | Demo A (local) | Demo B (GCP) | Notes |
|------|:--:|:--:|-------|
| `git` | yes | yes | clone the repo |
| **Python 3.12+** | yes | yes | the package pins `>=3.12` |
| Node.js 18+ and npm | for the UI / Playwright | for the UI | only if you show the browser console |
| **Playwright** (`pip install playwright` + `playwright install chromium`) | for the guided walkthrough | not needed | Demo A's presenter walkthrough only |
| A GCP project + `gcloud` | not needed | yes | billing enabled; `asia-southeast1` available |
| Terraform | not needed | yes | provisions BigQuery, GCS, the WORM log bucket, CMEK |
| Cloud KMS key (regional) | not needed | yes | CMEK; set `AI_QUALITY_KMS_KEY` |

Install/setup references (read these once):

- Local install and profiles -> [README 4.1 `local`](README.md#41-local-profile-a-working-offline-gate-no-gcp-runs-anywhere)
- GCP install and deploy -> [README 4.3 `gcp`](README.md#43-gcp-profile-real-managed-stack-in-asia-southeast1) and [`docs/runbook.md`](docs/runbook.md)
- Running the surfaces (API / CLI / UI) -> [README 5](README.md#5-running-the-three-surfaces)
- Deployment profiles explained -> [SPEC](SPEC.md)
- The demo scripts -> [`scripts/README.md`](scripts/README.md)
- The UI console -> [`ui/README.md`](ui/README.md)
- The gate pipeline -> [README 6](README.md#6-the-promotion-gate-a4--p-08) and [`ARCHITECTURE.md`](ARCHITECTURE.md)
- Config (`${ENV_VAR}` resolved at load) -> [`config/settings.yaml`](config/settings.yaml)

---

## 1. Common setup (both demos)

```bash
git clone https://github.com/portable-genai/model-quality-gate.git
cd model-quality-gate

python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # core + dev tooling (NO google-cloud-* packages)

# Sanity check the offline stack before presenting:
export AI_QUALITY_PROFILE=local
make lint test                   # ruff + mypy + pytest -m 'not integration' (all local, no cloud)
```

See [README 4.1](README.md#41-local-profile-a-working-offline-gate-no-gcp-runs-anywhere) for details.

---

## 2. Demo A: the promotion gate, offline (local)

The gate uses the deterministic `local` stack (SQLite FTS5 retrieval + a deterministic
scorer / judge + a heuristic red-team), so it needs **no Google Cloud and no API key**,
ideal for a laptop demo. Four ways to present it, in order of polish.

### 2.1 Guided, presenter-controlled walkthrough (recommended)

A real browser opens; the script narrates each step and **waits for you to press Enter**
before performing it, so you control the pace. (One-time: `pip install playwright &&
playwright install chromium`.)

```bash
# Terminal 1: the live demo server (http://localhost:8121)
source .venv/bin/activate
PYTHONPATH=src python scripts/model_quality_gate_demo_server.py

# Terminal 2: the guided walkthrough (a Chrome window opens)
source .venv/bin/activate
python scripts/model_quality_gate_demo_playwright.py
```

You'll step through, pressing Enter each time:

1. **Candidate submitted**: the target is `gemini-3.5-flash @ v3 : compliance-qa-golden`, system C1. Nothing gated yet.
2. **Run the gate**: the deterministic evaluation scores four metrics (groundedness,
   citation accuracy, faithfulness, safety) and the red-team battery runs five attack
   families. Both reports pass, while production promotion is denied because the laptop
   result has no managed attestation.
3. **Related reference context**: each golden question retrieves display-only
   Hrz2-compatible passages for auditor inspection. The deterministic local scorer does
   not consume this retrieval, so it is not causal score provenance.

**What to point at on screen:** the local-quality-pass / production-denied banner, the metric bars each clearing
their threshold marker, the red-team panel (every probe blocked), the sealed model card
(MRM evidence + limitations), and the related-reference page (must-cite ids vs retrieved passages).
Full options (`SLOWMO_MS`, `HEADLESS`, `CHROME_PATH`, ...) are in [`scripts/README.md`](scripts/README.md).

### 2.2 Manual, click-through (no Playwright)

Run only the server and drive it yourself in any browser:

```bash
PYTHONPATH=src python scripts/model_quality_gate_demo_server.py     # http://localhost:8121
```

Open `http://localhost:8121` and click **Run the gate ▶** to advance the real gate, **Next ▶**
to see the related reference context, **Restart** to reset. Same three steps as above.

Or drive the **real console** against the **real API** on the local profile:

```bash
# Terminal 1: the FastAPI gate on the local profile (offline, :8084)
make run-api PROFILE=local

# Terminal 2: the Next.js console (:3000), built and served the way it ships
cd ui && npm install && npm run build && npm run start
```

Every demo runs against a production build, never a development server. `make run-ui` is the
developer loop with hot reload, and it is not what a presenter shows.

Open `http://localhost:3000`, keep the defaults (`gemini-3.5-flash` / `v3` /
`compliance-qa-golden`) and click **Run promotion gate**. The header pill shows
`local · asia-southeast1`. The same form also runs **Evaluate only** and **Red-team only**.

### 2.3 Static artifacts (slides / screenshots)

Generate the audit-first pages and JSON without a browser:

```bash
PYTHONPATH=src python scripts/model_quality_gate_demo.py model_quality_gate_demo.json   # prints the stage-by-stage summary
PYTHONPATH=src python scripts/render_model_quality_gate_ui.py model_quality_gate_demo.json ./out
# -> ./out/ai-quality-verdict.html, ./out/ai-quality-references.html
# (or simply: make demo)
```

### 2.4 One-shot gate via the CLI (quick variant)

If you only want to show the verdict in a terminal (not the browser):

```bash
export AI_QUALITY_PROFILE=local
ai-quality gate gemini-3.5-flash v3 compliance-qa-golden
# or: make gate-local
```

Expected (abridged): EvalReport and RedTeamReport `PASS`, Promotion Gate `FAIL` because
the local evidence is not managed-attested. The raw CLI therefore exits 1; `make gate-local`
wraps it as an assertion-backed successful demo self-test. `ai-quality evaluate ...` and
`ai-quality redteam ...` show the individual artifacts.

---

## 3. Demo B: the promotion gate on the managed GCP stack

Shows the same gate contract producing the same artifacts against **real managed services**
in `asia-southeast1`. Follow [`docs/runbook.md`](docs/runbook.md) for the authoritative
deploy steps; the short version:

### 3.1 GCP setup

```bash
source .venv/bin/activate
pip install -e ".[gcp,dev]"                 # adds google-adk, google-genai, bigquery, storage, ...

export GOOGLE_CLOUD_PROJECT=your-sg-project
export AI_QUALITY_PROFILE=gcp
export AI_QUALITY_KMS_KEY="projects/.../locations/asia-southeast1/keyRings/.../cryptoKeys/..."
gcloud auth application-default login
```

### 3.2 Provision infra (one-time)

```bash
make tf-plan          # review the plan, the WORM log-bucket lock is IRREVERSIBLE
cd infra/terraform && terraform apply && cd ../..
```

Details and gotchas (region fail-fast, key rotation, retention): [`docs/runbook.md`](docs/runbook.md).

### 3.3 Run and show

```bash
make run-api          # FastAPI gate on :8084, profile=gcp
```

Then demo any surface ([README 5](README.md#5-running-the-three-surfaces)):

```bash
# REST: run the full gate and get the GateDecision with evidence.
# The audit actor is the server-verified identity, not a body field: in local mode add
# -H 'X-Dev-Persona: approver' to pick a seeded persona (default persona otherwise);
# in secure mode it comes from the IAP-verified assertion (docs/embedding-and-identity.md).
curl -s localhost:8084/v1/gate -H 'content-type: application/json' -d '{
  "target": {"model":"gemini-3.5-flash","prompt_version":"v3","dataset_id":"compliance-qa-golden","system":"C1"},
  "dataset_id": "compliance-qa-golden"
}' | python -m json.tool

# The cheap promotion check sibling pipelines poll (rule R5)
curl -s 'localhost:8084/v1/gate?model=gemini-3.5-flash&prompt_version=v3&dataset=compliance-qa-golden'

# Agent card / health
curl -s localhost:8084/.well-known/agent-card.json | python -m json.tool
curl -s localhost:8084/healthz
```

Or the browser console (talks to the API on :8084), see [`ui/README.md`](ui/README.md):

```bash
cd ui && npm install && npm run build && npm run start   # http://localhost:3000
```

**What to highlight:** a target passes only if **every** eval metric clears its threshold
**and every** red-team probe is blocked; a borderline pass sets `requires_human_review`
(maker-checker, P-06); every gate / eval / red-team action is written to the **WORM** log
bucket (P-07); tracing captures structure and token usage but **never** prompt/response
content; an empty golden dataset is a hard error, never a vacuous PASS; everything stays in
`asia-southeast1` with CMEK + VPC-SC ([README 7](README.md#7-security--residency-posture)).

> **Note.** Hrz4 does **not** process customer PII (it evaluates models against datasets), so
> rule R1 / the Hrz1 redaction step is N/A here: the audit records carry the target ref and a
> verdict summary, not user data.

---

## 4. Talking points

- **Eval-gated promotion (P-08).** No build in the catalog is promoted without passing Hrz4;
  every B/C agent calls this gate first (dependency rule R5). The gate is the product.
- **The verdict is deterministic and replayable.** Reconciling scores against thresholds
  and combining eval AND red-team into PASS/FAIL is pure domain logic (no LLM in the
  decision path); under `local` the scorer / judge / red-team are deterministic, so an
  auditor can replay the exact verdict.
- **Audit-first output.** Four artifacts behind every verdict: the EvalReport (per-metric
  score vs threshold), the RedTeamReport (per-probe blocked), the GateDecision (verdict +
  MRM pointers + caveats), and the versioned ModelCard. Related retrieved passages are
  display-only context for inspection, not causal evidence for those artifacts.
- **Guardrails hold.** WORM audit, tracing without content, maker-checker on borderline
  passes, no vacuous PASS on an empty dataset, single-region + CMEK residency, and a
  one-line profile switch to the on-prem migration target (P-02 / P-12).

---

## 5. Troubleshooting and cleanup

| Symptom | Fix |
|---------|-----|
| `python3.12: command not found` | Install Python 3.12+; the package pins `>=3.12`. |
| `ModuleNotFoundError: model_quality_gate` | Run from the repo root with `PYTHONPATH=src` (the scripts set the local profile themselves). |
| Playwright: "executable doesn't exist" | `playwright install chromium`, or set `CHROME_PATH=/path/to/chrome`. |
| No display for the headed walkthrough | Use 2.2 (manual browser) on a machine with a display, or `HEADLESS=1 DEMO_AUTO=1 python scripts/model_quality_gate_demo_playwright.py` to self-run. |
| "Cannot reach the demo server" | Start 2.1 Terminal 1 first; or set `DEMO_URL` if you changed `--port`. |
| Demo port 8121 / API port 8084 in use | `python scripts/model_quality_gate_demo_server.py --port 9000` (then `DEMO_URL=http://127.0.0.1:9000`); API port via `make run-api API_PORT=...`. |
| UI shows "backend offline" | Start the API first (`make run-api PROFILE=local`); the console expects it on :8084 (`NEXT_PUBLIC_API_BASE`). |
| CLI exits **2** with a migration message | You're on `AI_QUALITY_PROFILE=onprem` (fail-fast placeholders). Use `local` (Demo A) or `gcp` (Demo B). |
| CLI `gate` exits **1** | The gate ran but the target FAILED (a metric below threshold or a probe not blocked). That is a real verdict, not an error. |
| GCP deploy / region / VPC-SC errors | See [`docs/runbook.md`](docs/runbook.md). |

**Stop / clean up:** Ctrl-C the demo server and `make run-api`. For GCP, scale the
deployment to zero or remove the app SA's eval permissions. The WORM audit trail and the
sealed model cards remain intact. `make clean` removes local caches/artefacts; the demo JSON
and `./out` pages are plain files you can delete.
