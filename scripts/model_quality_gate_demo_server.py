"""Live, presenter-controlled demo server for the A4 promotion gate (stdlib only).

Holds a real :class:`PromotionGateService` on the offline ``local`` stack and runs the
*actual* gate for the candidate target one click at a time — submit target -> run the gate
-> show its reports plus display-only related references — then
Restart to reset. No Google Cloud, no API key, no extra dependencies.

    PYTHONPATH=src python scripts/model_quality_gate_demo_server.py [--port 8092]

Then open http://localhost:8092 and click "Run the gate ▶", or drive it with
``scripts/model_quality_gate_demo_playwright.py`` for a presenter-controlled walkthrough. The
demo port (8092) is deliberately distinct from the FastAPI gate port (8084).
"""

from __future__ import annotations

import argparse
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ.setdefault("AI_QUALITY_PROFILE", "local")

import model_quality_gate_demo as demo  # sibling script: reuse the synthetic candidate scenario  # noqa: E402
import render_model_quality_gate_ui as r  # sibling script: reuse the audit-first rendering  # noqa: E402

from model_quality_gate.api import deps  # noqa: E402
from model_quality_gate.config import Settings, build_container  # noqa: E402
from model_quality_gate.domain.models import EvalTarget  # noqa: E402
from model_quality_gate.domain.serialization import to_jsonable  # noqa: E402
from model_quality_gate.pipelines.datasets import (  # noqa: E402
    load_golden_dataset,
    standard_redteam_cases,
)

# The scripted demo steps. Each "Next" performs the action described by ``next``.
STEPS = [
    {
        "key": "target",
        "label": "Candidate submitted — model + prompt version + golden dataset",
        "next": "Run the promotion gate (eval + red-team) and seal the MRM evidence",
    },
    {
        "key": "verdict",
        "label": "Gate run — verdict, EvalReport, RedTeamReport and model card sealed",
        "next": "Show related reference context (display-only)",
    },
    {
        "key": "references",
        "label": "Related references — display-only retrieval per golden input",
        "next": None,
    },
]

_CONTROL_CSS = """
.democtl{position:sticky;top:0;z-index:10;display:flex;align-items:center;gap:12px;
  margin:-24px -18px 16px;padding:12px 18px;background:#0b101a;color:#fff}
.democtl .lbl{font-size:13px}.democtl .lbl b{color:#90b2ff}
.democtl .spacer{flex:1}
.democtl form{margin:0}
.democtl button{font:inherit;font-size:13px;font-weight:600;border:0;border-radius:7px;
  padding:7px 14px;cursor:pointer}
.democtl .next{background:#3a60f0;color:#fff}.democtl .next:disabled{opacity:.4;cursor:default}
.democtl .restart{background:transparent;color:#a6b6cc;border:1px solid #33445b}
.democtl .pct{font-variant-numeric:tabular-nums;color:#cdd7e4;font-size:12px}
"""


class DemoSession:
    """Drives the real promotion gate forward one scripted step at a time."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.settings = Settings.load()
        self.container = build_container(self.settings)
        self.gate_svc = deps.build_gate_service(self.container)
        self.card_svc = deps.build_model_card_service(self.container)
        self.idx = 0
        self.target = EvalTarget(
            model=demo.MODEL,
            prompt_version=demo.PROMPT_VERSION,
            dataset_id=demo.DATASET_ID,
            system=demo.SYSTEM,
        )
        self.dataset = load_golden_dataset(demo.DATASET_ID)
        self.data: dict = {
            "target": to_jsonable(self.target),
            "profile": self.settings.profile,
            "region": self.settings.region,
            "decision": None,
            "model_card": None,
            "references": [],
        }

    @property
    def at_end(self) -> bool:
        return self.idx >= len(STEPS) - 1

    def advance(self) -> None:
        if self.at_end:
            return
        self.idx += 1
        key = STEPS[self.idx]["key"]
        if key == "verdict" and self.data["decision"] is None:
            decision = self.gate_svc.gate(
                self.target, self.dataset, standard_redteam_cases(), actor="demo:server"
            )
            card = self.card_svc.get(self.target.model, self.target.prompt_version)
            self.data["decision"] = demo.decision_json(decision)
            self.data["model_card"] = to_jsonable(card) if card is not None else None
        elif key == "references" and not self.data["references"]:
            self.data["references"] = demo._related_references(self.container, self.dataset)

    # -- rendering --------------------------------------------------------- #
    def render(self) -> str:
        key = STEPS[self.idx]["key"]
        if key == "target":
            html = r.page("A4 gate demo — candidate", self._target_body())
        elif key == "verdict" and self.data["decision"]:
            html = r.render_verdict(self.data)
        elif key == "references" and self.data["references"]:
            html = r.render_references(self.data)
        else:  # pragma: no cover - defensive
            html = r.page("A4 gate demo", "<p>Nothing to show.</p>")
        return self._inject_controls(html)

    def _target_body(self) -> str:
        t = self.data["target"]
        ref = f"{t['model']}@{t['prompt_version']}:{t['dataset_id']}"
        cases = standard_redteam_cases()
        rows = "".join(
            f"<div class='kv'><span class='k'>{k}</span><span class='v mono'>{r.esc(v)}</span></div>"
            for k, v in [
                ("Model", t["model"]),
                ("Prompt version", t["prompt_version"]),
                ("Golden dataset", t["dataset_id"]),
                ("System under test", t.get("system") or "—"),
            ]
        )
        return (
            f"<h1>A4 promotion gate — candidate {r.esc(t['model'])}</h1>"
            f"<p class='sub'>Candidate <b class='mono'>{r.esc(ref)}</b> · profile <b>{r.esc(self.data['profile'])}</b> · "
            f"region <b>{r.esc(self.data['region'])}</b> · a candidate awaiting promotion. Not gated yet.</p>"
            "<section class='panel'><h2>Candidate under promotion"
            "<span class='statuspill' style='background:#e6ebf2;color:#546b8b'>PENDING</span></h2>"
            f"<div class='body'><div class='kv' style='grid-template-columns:170px 1fr;gap:6px 14px'>{rows}</div>"
            f"<p class='muted' style='margin-top:10px'>The gate will score {self.dataset.n_examples} golden "
            f"examples on four AI-quality metrics and run {len(cases)} adversarial probes; a target passes only "
            "if every metric clears its threshold and every probe is blocked.</p></div></section>"
            "<p class='foot'>Audit-first A4 gate view · synthetic fictional data · deterministic offline scorer / red-team</p>"
        )

    def _inject_controls(self, html: str) -> str:
        step = STEPS[self.idx]
        nxt = step["next"]
        badge = ""
        if self.data["decision"]:
            passed = self.data["decision"].get("passed")
            badge = f"<span class='pct'>verdict {'PASS' if passed else 'FAIL'}</span>"
        next_btn = (
            f"<form method='post' action='/advance'><button class='next' type='submit'>"
            f"{'Run the gate ▶' if step['key'] == 'target' else 'Next ▶'} &nbsp;·&nbsp; {r.esc(nxt)}</button></form>"
            if nxt
            else "<button class='next' disabled>Demo complete ✓</button>"
        )
        bar = (
            f"<div class='democtl' data-demo-step='{r.esc(step['key'])}'>"
            f"<span class='lbl'>Step {self.idx + 1}/{len(STEPS)} — <b>{r.esc(step['label'])}</b></span>"
            f"{badge}<span class='spacer'></span>{next_btn}"
            "<form method='post' action='/restart'><button class='restart' type='submit'>Restart</button></form>"
            "</div>"
        )
        html = html.replace("</style>", _CONTROL_CSS + "</style>", 1)
        return html.replace("<div class='wrap'>", "<div class='wrap'>" + bar, 1)


class Handler(BaseHTTPRequestHandler):
    session: DemoSession  # set on the server instance below

    def _send(self, body: str, status: int = 200) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _redirect(self, to: str = "/") -> None:
        self.send_response(303)
        self.send_header("Location", to)
        self.end_headers()

    @property
    def _sess(self) -> DemoSession:
        return self.server.session  # type: ignore[attr-defined]

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        with self.server.lock:  # type: ignore[attr-defined]
            if path == "/":
                self._send(self._sess.render())
            elif path == "/state":
                self._send(json.dumps({"step": self._sess.idx}), 200)
            elif path == "/restart":
                # Allowed over GET so the walkthrough can reset with a plain navigation.
                self._sess.reset()
                self._redirect("/")
            else:
                self._send("<h1>404</h1>", 404)

    def do_POST(self) -> None:  # noqa: N802 (http.server API)
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        with self.server.lock:  # type: ignore[attr-defined]
            if path == "/advance":
                self._sess.advance()
            elif path == "/restart":
                self._sess.reset()
        self._redirect("/")

    def log_message(self, *args: object) -> None:  # quiet console
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Live A4 promotion-gate demo server")
    parser.add_argument("--port", type=int, default=8092)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.session = DemoSession()  # type: ignore[attr-defined]
    server.lock = threading.Lock()  # type: ignore[attr-defined]
    print(f"A4 gate demo server on http://{args.host}:{args.port}  (Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    main()
