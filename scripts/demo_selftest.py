"""Browserless, deterministic regression for the presenter-controlled demo."""

from __future__ import annotations

import http.client
import json
import os
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path


def _request(connection: http.client.HTTPConnection, method: str, path: str) -> tuple[int, bytes]:
    connection.request(method, path)
    response = connection.getresponse()
    return response.status, response.read()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="hrz4-demo-") as tmp:
        root = Path(tmp)
        os.environ["AI_QUALITY_PROFILE"] = "local"
        for suffix, filename in {
            "DB": "knowledge.db",
            "AUDIT": "audit.db",
            "REGISTRY": "registry.db",
            "MODEL_CARDS": "cards.db",
            "METRICS": "metrics.db",
            "DATASETS": "datasets.db",
        }.items():
            os.environ[f"AI_QUALITY_LOCAL_{suffix}"] = str(root / filename)

        import model_quality_gate_demo_server as demo_server

        server = ThreadingHTTPServer(("127.0.0.1", 0), demo_server.Handler)
        server.session = demo_server.DemoSession()  # type: ignore[attr-defined]
        server.lock = threading.Lock()  # type: ignore[attr-defined]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = http.client.HTTPConnection(*server.server_address, timeout=20)
        checks: list[str] = []
        try:
            status, body = _request(connection, "GET", "/state")
            assert status == 200 and json.loads(body)["step"] == 0
            checks.append("initial-state")

            status, body = _request(connection, "GET", "/")
            page = body.decode()
            assert status == 200 and "PENDING" in page and "Run the promotion gate" in page
            assert "data-demo-step='target'" in page
            checks.append("candidate-page")

            status, _ = _request(connection, "POST", "/advance")
            assert status == 303
            status, state = _request(connection, "GET", "/state")
            assert status == 200 and json.loads(state)["step"] == 1
            decision = server.session.data["decision"]  # type: ignore[attr-defined]
            assert decision["eval_report"]["passed"] is True
            assert decision["redteam_report"]["passed"] is True
            metrics = decision["eval_report"]["results"]
            probes = decision["redteam_report"]["results"]
            assert {row["metric"] for row in metrics} == {
                "groundedness",
                "citation_accuracy",
                "faithfulness",
                "safety",
            }
            assert all(row["passed"] == (row["score"] >= row["threshold"]) for row in metrics)
            assert next(row for row in metrics if row["metric"] == "safety")["threshold"] == 0.99
            categories = [row["case"]["category"] for row in probes]
            assert len(categories) == 5 and len(set(categories)) == 5
            assert all(row["blocked"] and row["passed"] for row in probes)
            assert decision["eval_report"]["passed"]
            assert decision["eval_report"]["attested"] is False
            assert decision["redteam_report"]["passed"]
            assert decision["passed"] is False
            assert any("not attested" in caveat for caveat in decision["caveats"])
            assert server.session.data["model_card"] is not None  # type: ignore[attr-defined]
            checks.append("real-gate-local-denial")

            status, body = _request(connection, "GET", "/")
            page = body.decode()
            assert status == 200 and "LOCAL QUALITY PASS" in page
            assert "EvalReport" in page and "RedTeamReport" in page
            assert "data-demo-step='verdict'" in page
            assert 'data-demo-verdict="fail"' in page
            assert 'data-demo-eval-verdict="pass"' in page
            assert 'data-demo-redteam-verdict="pass"' in page
            checks.append("verdict-page")

            status, _ = _request(connection, "POST", "/advance")
            assert status == 303
            status, state = _request(connection, "GET", "/state")
            assert status == 200 and json.loads(state)["step"] == 2
            references = server.session.data["references"]  # type: ignore[attr-defined]
            assert references and any(row["citations"] for row in references)
            assert any(
                citation["page"] is not None for row in references for citation in row["citations"]
            )
            status, body = _request(connection, "GET", "/")
            page = body.decode()
            assert "data-demo-step='references'" in page
            assert 'data-demo-reference-count="5"' in page
            checks.append("display-references")

            status, _ = _request(connection, "GET", "/not-a-route")
            assert status == 404
            checks.append("unknown-route")

            narrative = (
                Path("DEMO.md").read_text()
                + Path("scripts/model_quality_gate_demo.py").read_text()
                + Path("scripts/model_quality_gate_demo_server.py").read_text()
                + Path("scripts/render_model_quality_gate_ui.py").read_text()
                + Path("scripts/model_quality_gate_demo_playwright.py").read_text()
                + Path("scripts/README.md").read_text()
                + Path("README.md").read_text()
            )
            for false_claim in (
                "self-grounded on the local KB index",
                "each grounded in cited reference passages",
                "grounding evidence behind the eval metrics",
                "grounding page",
                "Grounding evidence",
                "grounded evaluation",
                "each golden input cites",
            ):
                assert false_claim not in narrative
            checks.append("bounded-narration")

            status, _ = _request(connection, "POST", "/restart")
            assert status == 303
            assert server.session.idx == 0  # type: ignore[attr-defined]
            assert server.session.data["decision"] is None  # type: ignore[attr-defined]
            status, state = _request(connection, "GET", "/state")
            assert status == 200 and json.loads(state)["step"] == 0
            checks.append("restart")

            artifact = {
                "profile": "local",
                "checks": checks,
                "scope": (
                    "Real deterministic gate and presenter state transitions; "
                    "retrieved references are display context, not score provenance."
                ),
            }
            out = Path(os.environ.get("DEMO_SELFTEST_OUT", "out/demo-selftest.json"))
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(artifact, indent=2) + "\n")
            print(f"demo self-test PASS ({len(checks)} checks) -> {out}")
            return 0
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
