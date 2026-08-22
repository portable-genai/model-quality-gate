"""Executable, bounded proof of Hrz4's adapter-profile portability claims."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import replace
from pathlib import Path

from hex_service_kit import AuditChainError

from model_quality_gate.api import deps
from model_quality_gate.config import Container, LocalSettings, Settings
from model_quality_gate.domain.identity import RequestContext
from model_quality_gate.domain.models import EvalTarget
from model_quality_gate.domain.serialization import to_jsonable
from model_quality_gate.pipelines.datasets import load_golden_dataset, standard_redteam_cases

PORTS = {
    "identity",
    "evaluation",
    "redteam",
    "dataset_store",
    "prompt_registry",
    "model_card_store",
    "metrics_store",
    "knowledge_base",
    "llm",
    "audit",
    "tracer",
    "registry",
    "tool_catalog",
}
RUNTIME_PROFILES = {"gcp", "platform", "local", "onprem"}
REQUIRED_LIMIT_AXES = {
    "channel_ui",
    "runtime_controls",
    "policy",
    "jurisdiction_regulator",
    "tenant_object_authz",
    "full_data_exit",
    "live_integrations",
    "onprem_implementation",
}
NOT_VERIFIED = {
    "channel_ui": "UI, channel, or alternate delivery-surface portability",
    "runtime_controls": "runtime safety, guardrail, or enforcement portability",
    "policy": "metric-policy, threshold, bundle, or approval-policy portability",
    "jurisdiction_regulator": "jurisdiction packs or regulator crosswalk portability",
    "tenant_object_authz": (
        "identity-provider, tenant isolation, or object-authorization portability"
    ),
    "full_data_exit": ("full managed-data exit, backup/restore, or cross-store reconciliation"),
    "live_integrations": (
        "live GCP, IAP, sibling-platform HTTP, infrastructure, DNS, or key custody"
    ),
    "onprem_implementation": "a completed on-prem adapter implementation",
}


def _local_settings(base: Settings, root: Path) -> Settings:
    return replace(
        base,
        profile="local",
        local=LocalSettings(
            db_path=str(root / "knowledge.db"),
            audit_path=str(root / "audit.db"),
            registry_path=str(root / "registry.db"),
            model_cards_path=str(root / "cards.db"),
            metrics_path=str(root / "metrics.db"),
            datasets_path=str(root / "datasets.db"),
        ),
    )


def _run_local(base: Settings, root: Path) -> dict:
    settings = _local_settings(base, root)
    container = Container(settings)
    target = EvalTarget(
        model="gemini-3.5-flash",
        prompt_version="v3",
        dataset_id="compliance-qa-golden",
        system="C1",
    )
    analyst = container.identity.resolve(RequestContext())
    approver = container.identity.resolve(RequestContext(headers={"x-dev-persona": "approver"}))
    assert analyst.subject != approver.subject
    gate = deps.build_gate_service(container)
    first_decision = gate.gate(
        target,
        load_golden_dataset(target.dataset_id),
        standard_redteam_cases(),
        actor=analyst.actor,
    )
    decision = gate.gate(
        target,
        load_golden_dataset(target.dataset_id),
        standard_redteam_cases(),
        actor=approver.actor,
    )
    for result in (first_decision, decision):
        assert result.eval_report.passed and result.redteam_report.passed
        assert result.eval_report.attested is False
        assert result.passed is False
        assert any("not attested" in caveat for caveat in result.caveats)

    events = container.audit.read_all()
    assert [event["action"] for event in events] == [
        "evaluate",
        "redteam",
        "gate",
        "evaluate",
        "redteam",
        "gate",
    ]
    assert [event["actor"] for event in events[:3]] == [analyst.actor] * 3
    assert [event["actor"] for event in events[3:]] == [approver.actor] * 3
    assert container.audit.verify_chain().ok

    exported = root / "audit.jsonl"
    assert container.audit.export_jsonl(exported) == len(events)
    restored_settings = replace(
        settings,
        local=replace(settings.local, audit_path=str(root / "restored-audit.db")),
    )
    restored = Container(restored_settings).audit
    assert restored.import_jsonl(exported) == len(events)
    assert restored.read_all() == events and restored.verify_chain().ok

    tampered = root / "tampered-audit.jsonl"
    lines = exported.read_text().splitlines()
    middle = json.loads(lines[len(lines) // 2])
    middle["event"]["redacted_prompt"] += " TAMPERED"
    lines[len(lines) // 2] = json.dumps(middle, sort_keys=True, separators=(",", ":"))
    tampered.write_text("\n".join(lines) + "\n")
    tampered_settings = replace(
        settings,
        local=replace(settings.local, audit_path=str(root / "tampered-audit.db")),
    )
    try:
        Container(tampered_settings).audit.import_jsonl(tampered)
    except AuditChainError:
        pass
    else:  # pragma: no cover - a broken integrity gate
        raise AssertionError("tampered audit export was accepted")

    raw_dataset = b'{"id":"portable-fixture","input":"synthetic"}\n'
    container.dataset_store.put("portable-fixture", raw_dataset)
    assert Container(settings).dataset_store.get("portable-fixture") == raw_dataset
    card = container.model_card_store.get(target.model, target.prompt_version)
    reopened_card = Container(settings).model_card_store.get(target.model, target.prompt_version)
    assert card is not None and to_jsonable(reopened_card) == to_jsonable(card)
    return {
        "passed": decision.passed,
        "caveats": list(decision.caveats),
        "eval": {
            "passed": decision.eval_report.passed,
            "attested": decision.eval_report.attested,
            "dataset_version": decision.eval_report.dataset_version,
            "dataset_digest": decision.eval_report.dataset_digest,
            "results": [
                {
                    "metric": result.metric,
                    "score": result.score,
                    "threshold": result.threshold,
                    "passed": result.passed,
                }
                for result in decision.eval_report.results
            ],
        },
        "redteam": [
            {
                "category": result.case.category.value,
                "blocked": result.blocked,
                "passed": result.passed,
            }
            for result in decision.redteam_report.results
        ],
    }


def main() -> int:
    os.environ["AI_QUALITY_PROFILE"] = "local"
    base = Settings.load()
    assert set(NOT_VERIFIED) == REQUIRED_LIMIT_AXES
    assert set(base.adapters) == PORTS
    for name, binding in base.adapters.items():
        assert set(binding) == RUNTIME_PROFILES, (
            f"{name}: expected {RUNTIME_PROFILES}, got {set(binding)}"
        )

    constructed: dict[str, list[str]] = {}
    for profile in ("gcp", "platform"):
        names = sorted(base.adapters)
        profile_container = Container(replace(base, profile=profile))
        for name in names:
            profile_container._bind(name)  # noqa: SLF001 - executable wiring proof
        constructed[profile] = names

    with tempfile.TemporaryDirectory(prefix="hrz4-portability-") as tmp:
        root = Path(tmp)
        first = _run_local(base, root / "run-1")
        second = _run_local(base, root / "run-2")
        assert first == second, "local profile must replay deterministically"

    onprem = Container(replace(base, profile="onprem"))
    try:
        onprem.evaluation.score(
            EvalTarget(model="m", prompt_version="v1", dataset_id="d"),
            load_golden_dataset("compliance-qa-golden"),
            ["groundedness"],
        )
    except NotImplementedError:
        onprem_result = "fail-fast placeholder confirmed"
    else:  # pragma: no cover - a broken placeholder
        raise AssertionError("onprem evaluation unexpectedly executed")

    try:
        _ = Container(replace(base, profile="unknown-provider")).evaluation
    except KeyError:
        unknown_result = "unconfigured profile rejected"
    else:  # pragma: no cover - a dangerous managed fallback
        raise AssertionError("unknown profile silently selected an adapter")

    artifact = {
        "verified": {
            "profile_matrix": {name: sorted(value) for name, value in base.adapters.items()},
            "constructed_without_network_calls": constructed,
            "local": (
                "real quality and red-team checks with production promotion denied because "
                "managed attestation is unavailable; deterministic replay, dataset/card "
                "reopen, hash-chain export/import equality and tamper rejection, and "
                "distinct verified actors recorded in gate audit"
            ),
            "onprem": onprem_result,
            "unknown": unknown_result,
            "domain_artifact_format": "stdlib dataclasses serialized as JSON-safe values",
        },
        "not_verified": NOT_VERIFIED,
    }
    out = Path(os.environ.get("PORTABILITY_OUT", "out/portability-demo.json"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(artifact, indent=2) + "\n")
    print(f"portability demo PASS -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
