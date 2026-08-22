"""Presenter-controlled Playwright walkthrough of the live A4 gate demo.

Drives a headed browser through the promotion-gate flow served by
``scripts/model_quality_gate_demo_server.py``. It is **paced by the presenter**: before each step
it prints what is about to happen and waits for you to press Enter, then performs the
action (click "Run the gate ▶" / "Next ▶") and highlights the panel to look at. You stay
in control of timing.

Usage (two terminals)::

    # terminal 1 — the live demo server
    PYTHONPATH=src python scripts/model_quality_gate_demo_server.py

    # terminal 2 — the guided walkthrough (a real Chrome window opens)
    pip install playwright && playwright install chromium     # one-time
    python scripts/model_quality_gate_demo_playwright.py

It can also point at the live Next.js console (``make run-ui`` on :3000) instead of the
demo server: set ``DEMO_URL=http://127.0.0.1:3000`` and run with ``DEMO_AUTO=1`` to narrate
while you click the real UI yourself.

Environment overrides:
    DEMO_URL    server base URL (default http://127.0.0.1:8092)
    HEADLESS=1  run headless (used for the self-test; no window)
    DEMO_AUTO=1 don't wait for Enter — advance automatically (self-test / recording)
    SLOWMO_MS   per-action slow-motion in ms (default 250 headed, 0 headless)
    CHROME_PATH explicit Chromium/Chrome binary (else Playwright's own)
"""

from __future__ import annotations

import contextlib
import os
import sys
import time

from hex_service_kit.netdefaults import read_env_setting
from playwright.sync_api import sync_playwright


def _defaulted_setting(name: str, default: str) -> str:
    setting = read_env_setting(name)
    if setting.is_configured_empty:
        raise ValueError(
            f"{name} is set but empty; unset it to use {default!r}, or provide a value"
        )
    return setting.value or default


BASE = _defaulted_setting("DEMO_URL", "http://127.0.0.1:8092")
HEADLESS = os.environ.get("HEADLESS") == "1"
AUTO = os.environ.get("DEMO_AUTO") == "1"
SLOWMO = int(os.environ.get("SLOWMO_MS", "0" if HEADLESS else "250"))
CHROME_PATH = read_env_setting("CHROME_PATH").value or None

# (narration shown in the terminal, whether this step clicks "Next", panel to spotlight)
STEPS = [
    (
        "Candidate submitted. A target is a model + prompt version + golden dataset — here "
        "gemini-3.5-flash @ v3 against the compliance-qa-golden set. Nothing has been gated "
        "yet; this is the unit A4 promotes.",
        False,
        ".panel",
    ),
    (
        "Run the gate. The promotion gate runs the deterministic evaluation (groundedness, "
        "citation accuracy, faithfulness, safety) AND the five-family red-team battery, "
        "combines them into a PASS/FAIL verdict, and seals a model card as MRM evidence. "
        "Watch every metric bar clear its threshold and every probe come back blocked.",
        True,
        ".verdict",
    ),
    (
        "Related references. Each golden question retrieves display-only local KB context "
        "for auditor inspection. The deterministic scorer does not consume this retrieval, "
        "so the walkthrough does not claim it as causal score provenance.",
        True,
        ".panel",
    ),
]


def _pause(prompt: str) -> None:
    if AUTO:
        time.sleep(1.2)
        return
    try:
        input(prompt)
    except EOFError:  # non-interactive stdin
        time.sleep(1.0)


def _spotlight(page, selector: str | None) -> None:
    if not selector:
        return
    with contextlib.suppress(Exception):  # cosmetic only
        page.eval_on_selector_all(
            selector,
            "els => els.forEach((e,i)=>{ if(i<6){ e.style.transition='box-shadow .3s';"
            " e.style.boxShadow='0 0 0 3px #3a60f0'; setTimeout(()=>e.style.boxShadow='',1600);} })",
        )


def _reachable() -> bool:
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(BASE + "/state", timeout=2):
            return True
    except (urllib.error.URLError, OSError):
        return False


def main() -> int:
    if not _reachable():
        print(f"Cannot reach the demo server at {BASE}.")
        print("Start it first:  PYTHONPATH=src python scripts/model_quality_gate_demo_server.py")
        print("(Or point DEMO_URL at the live UI, e.g. DEMO_URL=http://127.0.0.1:3000.)")
        return 2

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS, slow_mo=SLOWMO, executable_path=CHROME_PATH)
        page = browser.new_context(viewport={"width": 1100, "height": 900}).new_page()

        print("\n=== A4 promotion-gate live demo — press Enter to advance each step ===\n")
        page.goto(BASE + "/restart", wait_until="load")  # always start clean
        page.goto(BASE + "/", wait_until="load")
        assert page.locator("[data-demo-step='target']").count() == 1

        for i, (say, click, spotlight) in enumerate(STEPS):
            print(f"[{i + 1}/{len(STEPS)}] {say}")
            _pause("        press Enter to run this step... ")
            if click:
                btn = page.locator(".democtl button.next")
                assert btn.count() == 1 and btn.is_enabled()
                btn.click()
                page.wait_for_load_state("load")
            page.wait_for_timeout(200)
            _spotlight(page, spotlight)
            page.wait_for_timeout(700)
            print()

        final_button = page.locator(".democtl button.next")
        assert final_button.count() == 1 and not final_button.is_enabled()

        print("Demo complete. The browser stays open for questions.")
        _pause("        press Enter to close the browser... ")
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
