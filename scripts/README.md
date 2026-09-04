# Demo scripts: `model-quality-gate` promotion gate

All scripts are SDK-free and run against the in-process `local` stack (SQLite FTS5
retrieval + deterministic scorer / judge + heuristic red-team: no Google Cloud, no API
key, no emulator). Run them from the repo root with the package on the path:

```bash
export AI_QUALITY_PROFILE=local
export PYTHONPATH=src
```

The scripts also set `AI_QUALITY_PROFILE=local` themselves (via `setdefault`), so they run
offline even if you forget the export. CI lints and formats them. The browserless
self-test is standard-library only; the optional headed walkthrough needs Playwright.

| Script | What it does |
|--------|--------------|
| `model_quality_gate_demo.py` | Runs the real gate and writes its decision, reports, model card and display-only related references. |
| `render_model_quality_gate_ui.py` | Renders gate-verdict and related-reference HTML pages. |
| `model_quality_gate_demo_server.py` | Runs the real gate one step per click (candidate -> verdict -> related references). |
| `model_quality_gate_demo_playwright.py` | A **presenter-controlled** Playwright walkthrough of the live server (or the live Next.js console): it narrates each step and waits for you to press Enter before performing it. |
| `demo_selftest.py` | Drives every loopback server step and asserts semantic markers and evidence. |
| `portability_demo.py` | Executes the bounded profile, adapter, identity and open-audit proof. |

## Static artifacts (slides / screenshots)

```bash
PYTHONPATH=src python scripts/model_quality_gate_demo.py model_quality_gate_demo.json
PYTHONPATH=src python scripts/render_model_quality_gate_ui.py model_quality_gate_demo.json ./out
# -> ./out/ai-quality-verdict.html, ./out/ai-quality-references.html
```

## Live, presenter-controlled demo

Two terminals:

```bash
# 1) the live demo server  (http://localhost:8092)
PYTHONPATH=src python scripts/model_quality_gate_demo_server.py

# 2) the guided walkthrough  (a real Chrome window opens)
pip install playwright && playwright install chromium      # one-time
python scripts/model_quality_gate_demo_playwright.py
```

The walkthrough is **paced by you**: it prints what the next step will do, waits for you to
press **Enter**, then clicks **Run the gate ▶** / **Next ▶** and spotlights the panel to look
at. The three steps are: candidate submitted -> gate run (verdict + eval + red-team + model
card) -> display-only related references.

You can also just open `http://localhost:8092` and click **Run the gate ▶** / **Restart** by
hand. The server holds the live gate service, so the buttons drive the same real flow.

The demo port is **8092**, deliberately distinct from the FastAPI gate port (**8084**) and
the Next.js UI port (**3000**), so all three can run side by side.

Useful environment overrides for `model_quality_gate_demo_playwright.py`:

| Var | Default | Purpose |
|-----|---------|---------|
| `DEMO_URL` | `http://127.0.0.1:8092` | server base URL (point at `http://127.0.0.1:3000` to narrate over the live console) |
| `HEADLESS=1` | off | run without a window (self-test / recording) |
| `DEMO_AUTO=1` | off | don't wait for Enter, advance automatically |
| `SLOWMO_MS` | `250` headed | per-action slow motion |
| `CHROME_PATH` | (none) | explicit Chromium/Chrome binary |
| `lock.py` | Compiles both lockfiles and puts the header back, because `uv pip compile` REPLACES the output file: it writes its own two-line provenance comment and destroys the `tag = commit` map the pin tests check against. `make lock` runs this rather than uv directly. |

## One-shot via `make`

```bash
make demo      # runs model_quality_gate_demo.py then render_model_quality_gate_ui.py into ./out
```
