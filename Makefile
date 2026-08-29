# A4 AI Quality & Model-Risk Platform : developer Makefile.
#
# The default test/lint/run targets run under the LOCAL profile: a WORKING offline stack
# (SQLite FTS5 + deterministic scorer / judge) that needs NO Google Cloud SDK and runs the
# gate end to end. Override PROFILE=gcp for the managed stack, or PROFILE=onprem to prove
# the fail-fast migration placeholders.

PYTHON      ?= python3
PYTHON      := $(if $(wildcard .venv/bin/python),.venv/bin/python,$(PYTHON))
PIP         ?= pip
PROFILE     ?= local
SRC         := src/model_quality_gate
TESTS       := tests
PY_SCOPE    := src tests eval scripts
API_APP     := model_quality_gate.api.app:app
API_HOST    ?= 127.0.0.1  # no-auth local dev binds loopback; override deliberately
API_PORT    ?= 8084
UI_DIR      := ui
TF_DIR      := infra/terraform

export AI_QUALITY_PROFILE := $(PROFILE)

.DEFAULT_GOAL := help
DEMO_PORT   ?= 8121
DEMO_OUT    ?= out

.PHONY: help install install-gcp fmt lint test eval eval-narrative gate-local demo demo-server demo-selftest portability-demo rename-selftest ui-check check run-api run-ui tf-plan clean

help: ## Show this help.
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Install the package + dev tooling (NO GCP SDK : local/test profile).
	$(PIP) install -e ".[dev]"

install-gcp: ## Install with the managed-stack extra (google-adk, genai, bigquery, ...).
	$(PIP) install -e ".[gcp,dev]"

fmt: ## Auto-format and auto-fix lint issues.
	$(PYTHON) -m ruff format $(PY_SCOPE)
	$(PYTHON) -m ruff check --fix $(PY_SCOPE)

lint: ## Lint (ruff) and type-check (mypy).
	# Deliberately scoped: .agents/skills contains canonical upstream tooling.
	$(PYTHON) -m ruff check $(PY_SCOPE)
	$(PYTHON) -m ruff format --check $(PY_SCOPE)
	$(PYTHON) -m mypy $(SRC)

test: ## Run unit + contract tests on the local profile (no GCP SDK required).
	AI_QUALITY_PROFILE=local $(PYTHON) -m pytest -m 'not integration' -q

eval: ## Run the A4 self-eval gate (gate_accuracy / threshold_correctness / redteam / safety).
	$(PYTHON) eval/run_eval.py

eval-narrative: ## Score narrative quality against the per-vertical floors (offline judge, no server).
	$(PYTHON) eval/run_narrative_eval.py

gate-local: ## Run the promotion gate end to end on the local profile (offline, real artifact).
	AI_QUALITY_PROFILE=local PYTHONPATH=src $(PYTHON) scripts/local_gate_selftest.py

demo: ## Run the offline gate demo and render the static audit-first HTML pages into $(DEMO_OUT)/.
	AI_QUALITY_PROFILE=local PYTHONPATH=src $(PYTHON) scripts/model_quality_gate_demo.py model_quality_gate_demo.json
	AI_QUALITY_PROFILE=local PYTHONPATH=src $(PYTHON) scripts/render_model_quality_gate_ui.py model_quality_gate_demo.json $(DEMO_OUT)

demo-server: ## Run the live, presenter-controlled gate demo server (offline) on :$(DEMO_PORT).
	AI_QUALITY_PROFILE=local PYTHONPATH=src $(PYTHON) scripts/model_quality_gate_demo_server.py --port $(DEMO_PORT)

demo-selftest: ## Drive every live presenter step over loopback and verify its evidence.
	AI_QUALITY_PROFILE=local PYTHONPATH=src:scripts $(PYTHON) scripts/demo_selftest.py

portability: portability-demo ## Standard fleet alias for the executable portability proof.

portability-demo: ## Execute the bounded adapter/profile portability proof.
	AI_QUALITY_PROFILE=local PYTHONPATH=src $(PYTHON) scripts/portability_demo.py

rename-selftest: ## Rename a clean copy, install locked deps, and run its full gate.
	$(PYTHON) scripts/rename_fork_selftest.py

ui-check: ## Build, execute and audit the production UI artifact.
	cd $(UI_DIR) && npm ci && npm run lint && npm test && NEXT_TELEMETRY_DISABLED=1 npm run build && npm run assert-hydratable && npm audit --audit-level=high

plugin: ## Render the Agent Plugins 1.0.0 directory from this repo's own declarations.
	python scripts/render_plugin.py --dest dist/plugin

mcp-serve: ## Serve the governed tool catalog over MCP 2026-07-28 (stdio; needs [gcp]).
	python -m model_quality_gate.mcp

check: lint test eval eval-narrative gate-local demo-selftest portability-demo ui-check plugin ## Run the full offline quality gate.

run-api: ## Run the FastAPI gate service (PROFILE=$(PROFILE)).
	uvicorn $(API_APP) --host $(API_HOST) --port $(API_PORT) --reload

run-ui: ## Run the React / Next.js UI (dev server).
	cd $(UI_DIR) && npm install && npm run dev

tf-check: ## Validate the Terraform posture offline (fmt + validate, NO cloud credentials).
	cd $(TF_DIR) && terraform fmt -check -recursive && terraform init -backend=false -input=false && terraform validate

tf-plan: ## Terraform plan for the configured regional infrastructure.
	cd $(TF_DIR) && terraform init -input=false && terraform plan

clean: ## Remove caches and build artefacts.
	rm -rf build dist *.egg-info .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
