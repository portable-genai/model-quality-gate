"""Gemini-driven adversarial red-team adapter (RedTeamPort).

Backs the domain ``RedTeamPort`` with a Gemini-driven harness: for each adversarial
probe it asks the target system to respond, then uses the judge model to assess whether
the target behaved safely (blocked / refused an attack that should be blocked, did not
fabricate for a hallucination probe). It maps the per-probe assessments onto a domain
``RedTeamReport``.

The ``google-genai`` SDK import is lazy so the on-prem and test profiles import without
it. This adapter sends only the synthetic probes (never customer data) to the model.
"""

from __future__ import annotations

import json
from typing import Any

from ...config import Settings
from ...domain._grounded import as_bool, parse_structured
from ...domain.models import (
    EvalTarget,
    LlmResponse,
    RedTeamCase,
    RedTeamReport,
    RedTeamResult,
)
from ...domain.prompts import REDTEAM_ASSESS_SYSTEM, REDTEAM_ASSESS_USER

_ASSESS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "blocked": {"type": "boolean"},
        "passed": {"type": "boolean"},
        "detail": {"type": "string"},
    },
    "required": ["blocked", "passed", "detail"],
}


class GeminiRedTeamAdapter:
    """Adversarial red-team harness backed by Gemini judge assessments."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: Any | None = None

    def _genai(self) -> Any:
        """Return (and cache) the google-genai client (lazy import)."""
        if self._client is None:
            from google import genai  # lazy

            self._client = genai.Client(
                vertexai=True,
                project=self._settings.project_id,
                # MODEL location, not the compute region.
                location=self._settings.models.location,
            )
        return self._client

    # ------------------------------------------------------------------ #
    # RedTeamPort
    # ------------------------------------------------------------------ #
    def run(self, target: EvalTarget, cases: list[RedTeamCase]) -> RedTeamReport:
        """Run the adversarial probes against ``target`` and assess each outcome."""
        results: list[RedTeamResult] = []
        for case in cases:
            response_text = self._elicit(target, case.probe)
            assessment = self._assess(case, response_text)
            results.append(assessment)
        return RedTeamReport(target=target, results=tuple(results))

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _elicit(self, target: EvalTarget, probe: str) -> str:
        """Send the adversarial probe to the target model and capture its response."""
        from google.genai import types  # lazy

        client = self._genai()
        result = client.models.generate_content(
            model=target.model or self._settings.models.reasoning,
            contents=probe,
            config=types.GenerateContentConfig(temperature=0.0),
        )
        return getattr(result, "text", "") or ""

    def _assess(self, case: RedTeamCase, response_text: str) -> RedTeamResult:
        """Judge whether the target safely handled the probe (judge model)."""
        from google.genai import types  # lazy

        client = self._genai()
        system = REDTEAM_ASSESS_SYSTEM
        user = REDTEAM_ASSESS_USER.format(
            category=case.category.value,
            expected_block=str(case.expected_block).lower(),
            probe=case.probe,
            response=response_text,
        )
        result = client.models.generate_content(
            model=self._settings.eval.judge_model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                temperature=0.0,
                response_mime_type="application/json",
                response_schema=_ASSESS_SCHEMA,
            ),
        )
        parsed = parse_structured(LlmResponse(text=_text_of(result)))
        blocked = as_bool(parsed.get("blocked"), default=False)
        passed = as_bool(parsed.get("passed"), default=False)
        detail = str(parsed.get("detail") or "")
        return RedTeamResult(case=case, blocked=blocked, detail=detail, passed=passed)


def _text_of(result: Any) -> str:
    text = getattr(result, "text", None)
    if isinstance(text, str) and text:
        return text
    return json.dumps({"blocked": False, "passed": False, "detail": "no judge response"})
