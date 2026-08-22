"""Runnable demo of the A4 promotion gate (synthetic, fictional data, fully offline).

Drives the *real* :class:`PromotionGateService` over the ``local`` profile (SQLite FTS5
retrieval + deterministic scorer / judge + heuristic red-team, SDK-free) for a candidate
target — a model + prompt version + golden dataset — and produces the four A4 artifacts:

    EvalReport  (per-metric score / threshold / passed)
    RedTeamReport (per-probe blocked / passed across five attack families)
    GateDecision  (the PASS/FAIL promotion verdict + maker-checker flag)
    ModelCard     (versioned MRM evidence behind the verdict)

Run it::

    PYTHONPATH=src python scripts/model_quality_gate_demo.py [out.json]

It prints a stage-by-stage summary and writes the full audit-view JSON (the gate decision,
the eval and red-team artifacts, related reference context for inspection, and the
model card) for the renderer / demo server to consume. No Google Cloud, no API key, no
emulator: the local evaluator, red-team adapter and fixture are deterministic.
"""

from __future__ import annotations

import json
import os
import sys

# The whole demo runs on the offline local stack. Set the profile before importing the
# container so config.Settings.load() resolves the local adapter bindings.
os.environ.setdefault("AI_QUALITY_PROFILE", "local")

from model_quality_gate.api import deps  # noqa: E402
from model_quality_gate.config import Settings, build_container  # noqa: E402
from model_quality_gate.domain.models import EvalTarget  # noqa: E402
from model_quality_gate.domain.serialization import (  # noqa: E402
    gate_decision_jsonable,
    to_jsonable,
)
from model_quality_gate.pipelines.datasets import (  # noqa: E402
    load_golden_dataset,
    standard_redteam_cases,
)

# The candidate under promotion (the same defaults the UI form and `make gate-local` use).
MODEL = "gemini-3.5-flash"
PROMPT_VERSION = "v3"
DATASET_ID = "compliance-qa-golden"
SYSTEM = "C1"  # the agent being promoted (free text on the target)
ACTOR = "demo:promotion-pipeline"


def _related_references(container, dataset) -> list[dict]:
    """Pull related A2 reference passages for each golden input.

    This is best-effort display enrichment for an auditor, not causal score provenance:
    the deterministic local scorer does not consume these retrieval results.
    """
    kb = container.knowledge_base
    out: list[dict] = []
    for example in dataset.examples:
        try:
            hits = kb.retrieve(example.input, top_k=3)
        except Exception:  # noqa: BLE001 - display enrichment only
            hits = []
        out.append(
            {
                "id": example.id,
                "input": example.input,
                "expected_points": list(example.expected_points),
                "must_cite_ids": list(example.must_cite_ids),
                "citations": [
                    {
                        "source_id": getattr(h, "source_id", ""),
                        "title": getattr(h, "title", ""),
                        "page": getattr(h, "page", None),
                    }
                    for h in hits
                ],
            }
        )
    return out


def decision_json(decision) -> dict:
    """Serialize a decision while retaining computed aggregate report verdicts.

    Kept as the demo's own name for the shared wrapper: the renderer reads both report
    verdicts straight off this dict, and the bare field walk does not carry them.
    """
    return gate_decision_jsonable(decision)


def main(out_path: str) -> int:
    settings = Settings.load()
    container = build_container(settings)
    gate_svc = deps.build_gate_service(container)
    card_svc = deps.build_model_card_service(container)

    target = EvalTarget(
        model=MODEL,
        prompt_version=PROMPT_VERSION,
        dataset_id=DATASET_ID,
        system=SYSTEM,
    )
    dataset = load_golden_dataset(DATASET_ID)
    cases = standard_redteam_cases()

    print(f"A4 promotion gate — candidate {target.ref}")
    print(f"  profile : {settings.profile}   region : {settings.region}")
    print(f"  golden dataset : {DATASET_ID}  ({dataset.n_examples} graded examples)")
    print(f"  red-team battery : {len(cases)} probes across five attack families\n")

    # 1) Run the real gate end to end (eval -> red-team -> verdict -> model card -> review).
    decision = gate_svc.gate(target, dataset, cases, actor=ACTOR)

    # 2) Eval artifact.
    print("-- EvalReport (AI-quality metrics vs promotion thresholds)")
    for r in decision.eval_report.results:
        mark = "ok  " if r.passed else "FAIL"
        print(f"   [{mark}] {r.metric:<18} {r.score:6.3f}  (threshold {r.threshold:.2f})")
    print(f"   examples scored : {decision.eval_report.n_examples}")
    print(f"   eval verdict    : {'PASS' if decision.eval_report.passed else 'FAIL'}\n")

    # 3) Red-team artifact.
    print("-- RedTeamReport (adversarial probes; safe == blocked)")
    for r in decision.redteam_report.results:
        mark = "safe  " if r.passed else "UNSAFE"
        print(f"   [{mark}] {r.case.category.value:<18} blocked={str(r.blocked).lower()}")
    print(f"   red-team verdict : {'PASS' if decision.redteam_report.passed else 'FAIL'}\n")

    # 4) Gate verdict + MRM evidence.
    verdict = "PASS" if decision.passed else "FAIL"
    print(f"-- GateDecision : {verdict}")
    print(f"   model card    : {decision.model_card_ref}")
    print(f"   MRM evidence  : {decision.mrm_evidence_ref}")
    print(
        f"   human review  : {'required (maker-checker, P-06)' if decision.requires_human_review else 'not required'}"
    )
    for caveat in decision.caveats:
        print(f"   caveat        : {caveat}")
    print()

    # 5) The model card the gate sealed as MRM evidence.
    card = card_svc.get(target.model, target.prompt_version)

    payload: dict = {
        "target": to_jsonable(target),
        "profile": settings.profile,
        "region": settings.region,
        "decision": decision_json(decision),
        "model_card": to_jsonable(card) if card is not None else None,
        "references": _related_references(container, dataset),
    }

    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    print(f"Wrote audit-view JSON -> {out_path}")
    # The laptop profile is expected to deny production promotion because it cannot
    # mint managed attestation. Producing that honest, inspectable decision is a
    # successful demo outcome even though the promotion verdict is FAIL.
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "model_quality_gate_demo.json"))
