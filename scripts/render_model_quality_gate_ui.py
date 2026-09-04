"""Render the audit-first A4 gate UI from the demo JSON into static HTML pages.

Server-side, dependency-free rendering of the gate decision produced by
``scripts/model_quality_gate_demo.py``: a verdict page (EvalReport + RedTeamReport + GateDecision
+ MRM model card) and a display-only related-reference page for auditor inspection.
Faithful to the console palette (ink / regblue, panels, metric bars, citation chips) so the
output doubles as slide-ready screenshots of the proposed console.

    PYTHONPATH=src python scripts/render_model_quality_gate_ui.py model_quality_gate_demo.json out_dir/
"""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path

METRIC_LABEL = {
    "groundedness": "Groundedness",
    "citation_accuracy": "Citation accuracy",
    "faithfulness": "Faithfulness",
    "safety": "Safety",
}
CATEGORY_LABEL = {
    "prompt_injection": "Prompt injection",
    "jailbreak": "Jailbreak",
    "pii_exfil": "PII exfiltration",
    "harmful_content": "Harmful content",
    "hallucination": "Hallucination",
}

CSS = """
:root{--ink-50:#f5f7fa;--ink-100:#e6ebf2;--ink-200:#cdd7e4;--ink-300:#a6b6cc;
--ink-400:#7790ae;--ink-500:#546b8b;--ink-600:#3f5470;--ink-700:#33445b;--ink-800:#1f2a3a;
--regblue-50:#eef4ff;--regblue-100:#dbe7ff;--regblue-600:#2945d6;--regblue-700:#2237ad;
--ok:#059669;--ok-bg:#ecfdf5;--warn:#d97706;--warn-bg:#fffbeb;--bad:#b91c1c;--bad-bg:#fee2e2;
--shadow:0 1px 2px rgba(11,16,26,.06),0 8px 24px rgba(11,16,26,.06);}
*{box-sizing:border-box}
body{margin:0;background:var(--ink-50);color:var(--ink-800);
font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;
font-size:14px;line-height:1.5;padding:24px 18px}
.wrap{max-width:880px;margin:0 auto}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
h1{font-size:18px;margin:0 0 2px}
.sub{color:var(--ink-500);font-size:13px;margin:0 0 16px}
.sub b{color:var(--ink-800)}
.nav{display:flex;gap:8px;margin:0 0 16px}
.nav a{font-size:12px;text-decoration:none;padding:4px 10px;border-radius:999px;border:1px solid var(--ink-200);background:#fff;color:var(--regblue-700)}
.verdict{display:flex;align-items:center;gap:12px;border-radius:10px;padding:14px 16px;margin-bottom:16px;font-weight:700;font-size:16px}
.verdict.pass{background:var(--ok-bg);border:1px solid #a7f3d0;color:#065f46}
.verdict.fail{background:var(--bad-bg);border:1px solid #fca5a5;color:var(--bad)}
.verdict .ref{font-weight:600;font-size:13px;color:var(--ink-600);margin-left:auto}
.review{border:1px solid #fcd34d;background:var(--warn-bg);color:#92400e;border-radius:8px;padding:8px 12px;font-size:12px;font-weight:600;margin-bottom:14px}
.panel{border:1px solid var(--ink-200);background:#fff;border-radius:10px;box-shadow:var(--shadow);margin-bottom:16px}
.panel>h2{border-bottom:1px solid var(--ink-100);padding:11px 16px;margin:0;font-size:13px;font-weight:600;color:var(--ink-800);display:flex;justify-content:space-between;align-items:center}
.panel>.body{padding:16px}
.statuspill{font-size:11px;font-weight:600;padding:2px 9px;border-radius:999px}
.pill.ok{background:var(--ok-bg);color:#065f46}.pill.bad{background:var(--bad-bg);color:var(--bad)}
/* metrics */
.metric{display:flex;align-items:center;gap:12px;padding:9px 0;border-bottom:1px solid var(--ink-100)}
.metric:last-child{border-bottom:0}
.metric .name{width:150px;font-weight:600;font-size:13px}
.metric .bar{flex:1;height:14px;border-radius:8px;background:var(--ink-100);overflow:hidden;border:1px solid var(--ink-200);position:relative}
.metric .bar>span{display:block;height:100%;background:linear-gradient(90deg,#3a60f0,#2945d6)}
.metric .bar>.thr{position:absolute;top:-2px;bottom:-2px;width:2px;background:var(--ink-600)}
.metric .vals{width:170px;text-align:right;font-variant-numeric:tabular-nums;font-size:12px;color:var(--ink-500)}
.metric .vals b{color:var(--ink-800)}
.metric .mk{font-size:10px;font-weight:700;text-transform:uppercase;padding:2px 7px;border-radius:5px;flex:none}
.mk.ok{background:var(--ok-bg);color:#065f46}.mk.bad{background:var(--bad-bg);color:var(--bad)}
/* probes */
.probe{display:flex;gap:10px;align-items:flex-start;padding:9px 0;border-bottom:1px solid var(--ink-100)}
.probe:last-child{border-bottom:0}
.probe .cat{font-weight:600;font-size:13px;width:140px;flex:none}
.probe .txt{font-size:13px;color:var(--ink-600)}
.probe .txt .d{color:var(--ink-400);font-size:12px;margin-top:2px}
.tag{font-family:ui-monospace,Menlo,monospace;font-size:11px;color:var(--regblue-700);background:var(--regblue-50);border:1px solid var(--regblue-100);border-radius:5px;padding:1px 6px}
.muted{color:var(--ink-400);font-size:12px}
.kv{display:grid;grid-template-columns:170px 1fr;gap:6px 14px;font-size:13px}
.kv .k{color:var(--ink-500)}
.kv .v{color:var(--ink-800)}
.chip{display:inline-flex;align-items:center;gap:4px;border:1px solid var(--ink-200);background:var(--ink-50);border-radius:6px;padding:1px 7px;font-size:11px;color:var(--ink-700);margin:2px 4px 2px 0}
.chip .ty{font-family:ui-monospace,Menlo,monospace;font-weight:600;color:var(--regblue-700)}
.chip .sr{font-family:ui-monospace,Menlo,monospace}
.q{border:1px solid var(--ink-200);border-radius:9px;padding:11px 12px;margin-bottom:10px}
.q .qin{font-weight:600;font-size:13px;margin-bottom:6px}
.q .ep{font-size:12px;color:var(--ink-500);margin-bottom:6px}
.foot{font-size:11px;color:var(--ink-400);text-align:center;margin-top:18px}
"""


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def page(title: str, body: str) -> str:
    return (
        f"<!doctype html><html><head><meta charset='utf-8'><title>{esc(title)}</title>"
        f"<style>{CSS}</style></head><body><div class='wrap'>{body}</div></body></html>"
    )


def _nav(active: str) -> str:
    links = [
        ("verdict", "Gate verdict", "ai-quality-verdict.html"),
        ("references", "Related references", "ai-quality-references.html"),
    ]
    return (
        '<div class="nav">'
        + "".join(
            f'<a href="{esc(href)}" style="{"font-weight:700;background:#eef4ff" if key == active else ""}">{esc(label)}</a>'
            for key, label, href in links
        )
        + "</div>"
    )


def _header(data: dict) -> str:
    t = data["target"]
    ref = f"{t['model']}@{t['prompt_version']}:{t['dataset_id']}"
    return (
        f"<h1>A4 promotion gate — {esc(t['model'])}</h1>"
        f"<p class='sub'>Candidate <b class='mono'>{esc(ref)}</b> · system <b>{esc(t.get('system') or '—')}</b> · "
        f"profile <b>{esc(data.get('profile'))}</b> · region <b>{esc(data.get('region'))}</b></p>"
    )


def render_metrics(eval_report: dict) -> str:
    rows = []
    for r in eval_report.get("results", []):
        score = float(r.get("score", 0.0))
        thr = float(r.get("threshold", 0.0))
        ok = bool(r.get("passed"))
        rows.append(
            f"""<div class="metric">
              <span class="mk {"ok" if ok else "bad"}">{"pass" if ok else "fail"}</span>
              <span class="name">{esc(METRIC_LABEL.get(r["metric"], r["metric"]))}</span>
              <span class="bar"><span style="width:{round(score * 100)}%"></span>
                <span class="thr" style="left:{round(thr * 100)}%" title="threshold {thr:.2f}"></span></span>
              <span class="vals">score <b>{score:.3f}</b> · threshold {thr:.2f}</span>
            </div>"""
        )
    verdict = "ok" if eval_report.get("passed") else "bad"
    label = "PASS" if eval_report.get("passed") else "FAIL"
    return (
        f'<section class="panel" data-demo-eval-verdict="{"pass" if eval_report.get("passed") else "fail"}"><h2>EvalReport — AI-quality metrics vs promotion thresholds'
        f'<span class="statuspill pill {verdict}">{label}</span></h2>'
        f'<div class="body">{"".join(rows)}'
        f'<p class="muted" style="margin-top:10px">Scored over {esc(eval_report.get("n_examples"))} graded golden examples. '
        "The marker on each bar is the promotion threshold; the fill is the achieved "
        "score.</p></div></section>"
    )


def render_redteam(redteam_report: dict) -> str:
    rows = []
    for r in redteam_report.get("results", []):
        ok = bool(r.get("passed"))
        case = r.get("case") or {}
        category = case.get("category", "")
        probe_id = case.get("id", "")
        rows.append(
            f"""<div class="probe">
              <span class="cat">{esc(CATEGORY_LABEL.get(category, category))}</span>
              <div class="txt"><span class="mk {"ok" if ok else "bad"}">{"safe" if ok else "unsafe"}</span>
                &nbsp;blocked={esc(str(r.get("blocked")).lower())}
                <div class="d">{esc(r.get("detail") or "")} <span class="mono muted">{esc(probe_id)}</span></div></div>
            </div>"""
        )
    verdict = "ok" if redteam_report.get("passed") else "bad"
    label = "PASS" if redteam_report.get("passed") else "FAIL"
    return (
        f'<section class="panel" data-demo-redteam-verdict="{"pass" if redteam_report.get("passed") else "fail"}"><h2>RedTeamReport — adversarial probes (safe == blocked)'
        f'<span class="statuspill pill {verdict}">{label}</span></h2>'
        f'<div class="body">{"".join(rows)}</div></section>'
    )


def render_card(card: dict | None) -> str:
    if not card:
        return ""
    metrics = "".join(
        f'<span class="chip"><span class="ty">{esc(METRIC_LABEL.get(k, k))}</span><span class="sr">{float(v):.3f}</span></span>'
        for k, v in (card.get("metrics") or {}).items()
    )
    lims = card.get("limitations") or []
    lim_html = (
        "".join(f"<li>{esc(x)}</li>" for x in lims)
        if lims
        else "<li class='muted'>none recorded — every metric cleared its threshold</li>"
    )
    return (
        '<section class="panel"><h2>ModelCard — MRM evidence sealed by the gate</h2><div '
        'class="body">'
        '<div class="kv">'
        f'<span class="k">Model @ version</span><span class="v mono">{esc(card.get("model"))}@{esc(card.get("version"))}</span>'
        f'<span class="k">Intended use</span><span class="v">{esc(card.get("intended_use"))}</span>'
        f'<span class="k">Owner</span><span class="v">{esc(card.get("owner"))}</span>'
        f'<span class="k">Created</span><span class="v mono">{esc(card.get("created_at"))}</span>'
        "</div>"
        f'<p style="margin:12px 0 4px"><b>Recorded metrics</b></p><div>{metrics}</div>'
        f'<p style="margin:12px 0 4px"><b>Limitations</b></p><ul style="margin:0">{lim_html}</ul>'
        "</div></section>"
    )


def render_verdict(data: dict) -> str:
    d = data["decision"]
    t = d["target"]
    ref = f"{t['model']}@{t['prompt_version']}:{t['dataset_id']}"
    passed = bool(d.get("passed"))
    requires_review = bool(d.get("requires_human_review"))
    attested = bool(d.get("eval_report", {}).get("attested"))
    quality_passed = bool(d.get("eval_report", {}).get("passed")) and bool(
        d.get("redteam_report", {}).get("passed")
    )
    if not passed and quality_passed and not attested:
        outcome = "LOCAL QUALITY PASS — production promotion denied: no managed attestation"
    elif passed and requires_review:
        outcome = "REFERENCE PASS — eligible after model-risk approval"
    elif passed:
        outcome = "REFERENCE PASS — eligible; no promotion action executed"
    else:
        outcome = "REFERENCE FAIL — not eligible"
    verdict = (
        f'<div class="verdict {"pass" if passed else "fail"}" data-demo-verdict="{"pass" if passed else "fail"}">'
        f"{outcome}"
        f'<span class="ref mono">{esc(ref)}</span></div>'
    )
    review = (
        '<div class="review">HUMAN REVIEW REQUIRED — maker-checker gate (P-06). '
        "A model-risk officer must sign off before promotion.</div>"
        if d.get("requires_human_review")
        else ""
    )
    evidence = (
        '<section class="panel"><h2>GateDecision — verdict &amp; MRM pointers</h2><div '
        'class="body"><div class="kv">'
        f'<span class="k">Verdict</span><span class="v"><b>{"PASS" if passed else "FAIL"}</b></span>'
        f'<span class="k">Model card ref</span><span class="v mono">{esc(d.get("model_card_ref"))}</span>'
        f'<span class="k">MRM evidence ref</span><span class="v mono">{esc(d.get("mrm_evidence_ref"))}</span>'
        f'<span class="k">Human review</span><span class="v">{"required (P-06)" if d.get("requires_human_review") else "not required"}</span>'
        "</div>"
        + (
            '<p style="margin:12px 0 4px"><b>Caveats</b></p><ul style="margin:0">'
            + "".join(f"<li>{esc(c)}</li>" for c in (d.get("caveats") or []))
            + "</ul>"
        )
        + "</div></section>"
    )
    body = (
        _header(data)
        + _nav("verdict")
        + verdict
        + review
        + evidence
        + render_metrics(d["eval_report"])
        + render_redteam(d["redteam_report"])
        + render_card(data.get("model_card"))
        + "<p class='foot'>Audit-first A4 gate view · synthetic fictional data · deterministic offline scorer / red-team</p>"
    )
    return page("A4 gate verdict", body)


def render_references(data: dict) -> str:
    rows = []
    for q in data.get("references", []):
        cites = (
            "".join(
                f'<span class="chip"><span class="ty">KB</span><span class="sr">{esc(c.get("source_id"))}</span></span>'
                for c in q.get("citations", [])
            )
            or "<span class='muted'>no reference passages returned</span>"
        )
        must = "".join(
            f'<span class="chip"><span class="ty">MUST-CITE</span><span class="sr">{esc(mid)}</span></span>'
            for mid in q.get("must_cite_ids", [])
        )
        points = "".join(f"<li>{esc(p)}</li>" for p in q.get("expected_points", []))
        rows.append(
            f"""<div class="q">
              <div class="qin">{esc(q.get("id"))} · {esc(q.get("input"))}</div>
              {f'<ul class="ep" style="margin:0 0 6px;padding-left:18px">{points}</ul>' if points else ""}
              <div style="margin-bottom:4px"><span class="muted">retrieved reference passages: </span>{cites}</div>
              <div>{must}</div>
            </div>"""
        )
    body = (
        _header(data)
        + _nav("references")
        + f'<section class="panel" data-demo-reference-count="{len(rows)}"><h2>Related reference context per golden input</h2>'
        f'<div class="body">{"".join(rows)}'
        '<p class="muted" style="margin-top:8px">These display-only passages are returned by '
        "the local enterprise-knowledge-base-compatible adapter for auditor inspection. The "
        "deterministic local scorer "
        "does not consume this retrieval, so it is not causal score provenance.</p></div></section>"
        "<p class='foot'>Audit-first A4 gate view · synthetic fictional data</p>"
    )
    return page("A4 related references", body)


def main(json_path: str, out_dir: str) -> None:
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    written = []
    p = out / "ai-quality-verdict.html"
    p.write_text(render_verdict(data), encoding="utf-8")
    written.append(p)
    g = out / "ai-quality-references.html"
    g.write_text(render_references(data), encoding="utf-8")
    written.append(g)
    for path in written:
        print("wrote", path)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
