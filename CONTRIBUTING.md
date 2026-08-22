# Contributing

Thanks for your interest in the Hrz4 AI Quality & Model-Risk Platform reference build. This
is a public engineering-portfolio piece, but it is held to production standards: every
change must pass the same gate CI enforces.

## Setup

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"        # core + dev tooling, NO google-cloud-* packages
export AI_QUALITY_PROFILE=onprem
```

No Google Cloud SDK is needed for development or the test suite: the domain runs under the
`onprem` profile with in-memory fakes.

## The gate (must be green before you push)

```bash
make lint        # ruff check + ruff format --check + mypy src
make test        # pytest -m 'not integration' (unit + contract)
make eval        # the Hrz4 self-eval gate (eval/run_eval.py)
```

Equivalently:

```bash
ruff check src tests
ruff format --check src tests
pytest -m 'not integration' -q
mypy src
python eval/run_eval.py
```

`ruff check`, `ruff format --check`, and `pytest -m 'not integration'` passing are
mandatory. `mypy` and the eval gate should also pass.

## Architecture rules (do not break these)

- **Keep the domain pure.** Nothing under [`src/model_quality_gate/domain/`](src/model_quality_gate/domain/)
  may import `google-cloud-*`, `google-adk`, `google-genai`, FastAPI, `httpx`, or pydantic.
  The domain is standard library only.
- **Keep GCP imports lazy.** Every `google-*` import in a `gcp` adapter must be inside a
  method or `__init__` (or under `TYPE_CHECKING`), never at module top level. Importing any
  module under the `onprem` profile must not require a Google Cloud SDK.
- **One adapter constructor shape.** Every adapter is `def __init__(self, settings: Settings)`.
- **Add a port the right way.** A new port is a `@runtime_checkable` `Protocol` re-exported
  from `ports/__init__.py`, with `gcp` + `onprem` (and `platform` if a sibling backs it)
  bindings in `config/settings.yaml`, plus an entry in the contract test.
- **No vacuous PASS.** The gate must never wave a target through unevaluated: an empty
  dataset is a hard error, and a backend failure is a failing report.

## Tests

- `tests/unit/` : real tests of each domain service driven by in-memory fakes.
- `tests/contract/test_port_parity.py` : proves every on-prem stub satisfies its Protocol.
- `tests/integration/` : marked `@pytest.mark.integration`, deselected by default; they
  require real GCP credentials and the `[gcp]` extra.

## Commit / PR conventions

- Keep changes focused; update `SPEC.md` if you change a contract.
- Markdown: avoid em-dashes; validate any mermaid diagram with `mmdc` before committing.
- This repo is licensed Apache-2.0; by contributing you agree your contribution is too.
