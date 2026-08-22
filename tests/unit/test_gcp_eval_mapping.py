from __future__ import annotations

from model_quality_gate.adapters.gcp.genai_eval import (
    _extract_artifact_refs,
    _extract_example_evidence,
    _extract_summary_scores,
)


def test_managed_eval_result_preserves_redacted_row_evidence() -> None:
    result = {
        "summary_metrics": {
            "groundedness/mean": 0.91,
            "safety/mean": 0.98,
        },
        "metrics_table": [
            {
                "id": "case-1",
                "prompt": "must not be copied",
                "response": "must not be copied",
                "groundedness/score": 0.83,
                "groundedness/verdict": "PASS",
                "groundedness/rationale": "Claims are supported.",
                "safety/score": 1.0,
                "safety/verdict": "PASS",
                "trace_id": "trace-123",
            }
        ],
        "resource_name": "projects/p/locations/us-central1/evaluations/run-1",
    }

    assert _extract_summary_scores(result, ["groundedness", "safety"]) == {
        "groundedness": 0.91,
        "safety": 0.98,
    }
    evidence = _extract_example_evidence(result, ["groundedness", "safety"])
    assert [(item.example_id, item.metric, item.passed) for item in evidence] == [
        ("case-1", "groundedness", True),
        ("case-1", "safety", True),
    ]
    assert evidence[0].detail == "managed-rationale-available-in-governed-artifact"
    assert evidence[0].trace_ref == "trace-123"
    assert all("must not be copied" not in repr(item) for item in evidence)
    assert _extract_artifact_refs(result) == ("projects/p/locations/us-central1/evaluations/run-1",)


def test_managed_rationale_content_is_never_copied_into_portable_evidence():
    result = {
        "rows": [
            {
                "id": "case-pii",
                "groundedness_score": 0.8,
                "groundedness_rationale": (
                    "Quoted prompt for jane.customer@example.com account 123456789"
                ),
            }
        ]
    }

    evidence = _extract_example_evidence(result, ["groundedness"])

    assert len(evidence) == 1
    assert "jane.customer" not in evidence[0].detail
    assert "123456789" not in evidence[0].detail
    assert evidence[0].detail == "managed-rationale-available-in-governed-artifact"
