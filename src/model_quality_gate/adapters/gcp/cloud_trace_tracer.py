"""Cloud Trace tracer adapter (ObservabilityTracerPort).

Backs the domain ``ObservabilityTracerPort`` with **Cloud Trace via OpenTelemetry**.
Spans capture the structure and token usage of the evaluation loop, but **message
content capture is OFF**: spans never carry prompt/response text. The OpenTelemetry /
exporter imports are lazy so the on-prem and test profiles import without them.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from ...config import Settings
from ...domain.models import TokenUsage


class CloudTraceTracerAdapter:
    """OpenTelemetry tracer exporting to Cloud Trace (content capture OFF)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._tracer: Any | None = None
        self._meter: Any | None = None

    def _otel_tracer(self) -> Any:
        if self._tracer is None:
            from opentelemetry import trace  # lazy
            from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter  # lazy
            from opentelemetry.sdk.trace import TracerProvider  # lazy
            from opentelemetry.sdk.trace.export import BatchSpanProcessor  # lazy

            provider = TracerProvider()
            exporter = CloudTraceSpanExporter(project_id=self._settings.project_id)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            trace.set_tracer_provider(provider)
            self._tracer = trace.get_tracer("model_quality_gate")
        return self._tracer

    # ------------------------------------------------------------------ #
    # ObservabilityTracerPort
    # ------------------------------------------------------------------ #
    @contextmanager
    def span(self, name: str, **attributes: str):  # -> Iterator[None]
        tracer = self._otel_tracer()
        # Only structural attributes are attached; never message content (PII safety).
        with tracer.start_as_current_span(name) as span:
            for key, value in attributes.items():
                span.set_attribute(key, value)
            yield

    def record_token_usage(self, usage: TokenUsage, model: str) -> None:
        """Emit token counts as span attributes for FinOps dashboards."""
        from opentelemetry import trace  # lazy

        span = trace.get_current_span()
        if span is None:
            return
        span.set_attribute("genai.usage.input_tokens", usage.input_tokens)
        span.set_attribute("genai.usage.output_tokens", usage.output_tokens)
        span.set_attribute("genai.usage.thinking_tokens", usage.thinking_tokens)
        span.set_attribute("genai.model", model)
