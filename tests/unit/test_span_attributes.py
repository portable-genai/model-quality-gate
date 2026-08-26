"""Span ATTRIBUTES carry structure, never content, and this is the test that can tell.

The conftest ``RecordingTracer`` records span NAMES (``self.spans.append(name)``), which is
right for the tests that assert a service opened its span and structurally blind to the one
defect that matters here: it throws the attributes away, so a span that started carrying a
golden example's question, a red-team probe or a prompt template would keep every existing
test green. A trace backend is not the WORM audit trail. It has no redaction stage, a wider
read audience and no retention rule written against a regulator's requirement, so an
attribute is OUTSIDE the boundary the audit sink holds (P-04).

A4 opens spans from five domain sites. Rather than enumerate five bespoke drivers, this
module drives the two REAL request paths that reach all five:

* ``gate_service.gate(...)`` : the promotion gate, which internally runs the evaluation and
  the red-team service, so one call covers ``gate.gate``, ``evaluation.evaluate`` and
  ``redteam.run``;
* ``prompt_service.register(...)`` and ``model_card_service.put(...)`` : the two MRM
  change-control writes, which no other path reaches (``prompt.register``,
  ``model_card.put``).

The union is asserted below, so a sixth span site added without a decision here fails.
"""

from __future__ import annotations

import pytest
from tests.fixtures import sample_targets

from model_quality_gate.adapters.local.tracer import LocalNoopTracerAdapter
from model_quality_gate.config import Settings
from model_quality_gate.domain.models import ModelCard

ACTOR = "model-risk@bank.test"
TARGET = sample_targets.SAMPLE_TARGET
DATASET = sample_targets.SAMPLE_DATASET
CASES = sample_targets.SAMPLE_REDTEAM_CASES

#: The complete attribute key set an A4 span may carry, per span name. Widening one of
#: these is a decision about what leaves the trust boundary, so it is made here rather
#: than at a call site.
_ALLOWED = {
    "gate.gate": {"action", "actor", "target"},
    "evaluation.evaluate": {"action", "actor", "target"},
    "redteam.run": {"action", "actor", "target"},
    "prompt.register": {"action", "actor", "prompt"},
    "model_card.put": {"action", "actor", "model"},
}

#: Evaluated content that exists in the fixtures and must never reach a span attribute:
#: the graded question, the adversarial probe, the reference snippet, the prompt body.
_CONTENT = (
    sample_targets.SAMPLE_DATASET.examples[0].input,
    sample_targets.SAMPLE_DATASET.examples[1].input,
    sample_targets.SAMPLE_REDTEAM_CASES[0].probe,
    sample_targets.SAMPLE_REDTEAM_CASES[2].probe,
    sample_targets.SAMPLE_CITATIONS[0].snippet,
    sample_targets.SAMPLE_PROMPT.template,
)

_CARD = ModelCard(
    model="gemini-3.7-flash",
    version="v3",
    intended_use="Compliance Q&A grounding evaluation.",
    metrics={"groundedness": 0.91},
    limitations=("English-only reference corpus",),
)


class _AttributeRecordingTracer(LocalNoopTracerAdapter):
    """Keeps (name, attributes) per span, unlike the name-only conftest recorder."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.spans: list[tuple[str, dict[str, str]]] = []

    def span(self, name: str, **attributes: str):  # type: ignore[no-untyped-def]
        self.spans.append((name, dict(attributes)))
        return super().span(name, **attributes)


@pytest.fixture
def tracer(local_settings) -> _AttributeRecordingTracer:  # type: ignore[override]
    """Override the conftest tracer so every service fixture assembles with THIS one."""
    return _AttributeRecordingTracer(local_settings)


def _drive_every_span_site(gate_service, prompt_service, model_card_service) -> None:
    gate_service.gate(TARGET, DATASET, CASES, actor=ACTOR)
    prompt_service.register(sample_targets.SAMPLE_PROMPT, actor=ACTOR)
    model_card_service.put(_CARD, actor=ACTOR)


def test_the_request_paths_open_exactly_the_known_spans(
    gate_service, prompt_service, model_card_service, tracer
) -> None:
    _drive_every_span_site(gate_service, prompt_service, model_card_service)
    names = {name for name, _ in tracer.spans}
    assert names == set(_ALLOWED), (
        "the set of spans these request paths open changed; a new span site is a "
        "trust-boundary decision, so record it in _ALLOWED here deliberately"
    )


def test_every_span_carries_allowlisted_keys_only(
    gate_service, prompt_service, model_card_service, tracer
) -> None:
    _drive_every_span_site(gate_service, prompt_service, model_card_service)
    assert tracer.spans, "the request paths opened no span at all"
    for name, attributes in tracer.spans:
        assert name in _ALLOWED, f"unexpected span {name!r}; add it here deliberately"
        assert set(attributes) == _ALLOWED[name], (
            f"span {name!r} attribute keys changed; widening the set is a trust-boundary "
            "decision, so update _ALLOWED here deliberately"
        )


def test_no_span_attribute_carries_evaluated_content(
    gate_service, prompt_service, model_card_service, tracer
) -> None:
    """Questions, probes, retrieved snippets and prompt bodies stay out of the trace."""
    _drive_every_span_site(gate_service, prompt_service, model_card_service)
    emitted = " ".join(value for _, attributes in tracer.spans for value in attributes.values())
    for content in _CONTENT:
        assert content not in emitted, f"span attribute leaked evaluated content: {content!r}"


def test_every_attribute_value_is_a_string(
    gate_service, prompt_service, model_card_service, tracer
) -> None:
    """The port declares str values; a structured object smuggles content past a grep."""
    _drive_every_span_site(gate_service, prompt_service, model_card_service)
    for name, attributes in tracer.spans:
        for key, value in attributes.items():
            assert isinstance(value, str), f"span {name!r} attribute {key!r} is not a str"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
