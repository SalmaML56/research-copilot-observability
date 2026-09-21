"""
Phase 5, step 33: GenAI metrics instrumentation.

OpenInference's LangChainInstrumentor only emits TRACES, never metrics -
verified directly against its source code (_instrument() only accepts
tracer_provider, no meter_provider parameter exists). The two OTel GenAI
semconv metrics this step requires (gen_ai.client.token.usage,
gen_ai.client.operation.duration) do not get generated anywhere by the
existing instrumentation, so they are built here manually via a LangChain
callback handler - the same extension point Langfuse's own CallbackHandler
uses, so this does not conflict with existing tracing/callbacks.

Metric spec (verified against OTel semconv registry):
  gen_ai.client.token.usage       Histogram, unit "{token}"
  gen_ai.client.operation.duration Histogram, unit "s"

Known gotcha (do not repeat): response.llm_output["model_provider"] from
ChatDeepSeek reports "openai" (misleading - DeepSeek is implemented as an
OpenAI-compatible wrapper internally). gen_ai.provider.name is therefore
derived from our OWN settings.model_profile, not from response metadata.
"""

import time
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from opentelemetry import metrics
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource

from research_copilot.config.settings import settings
from research_copilot.observability.identity import _current_identity

_meter_provider: MeterProvider | None = None
_token_usage_histogram = None
_operation_duration_histogram = None


def setup_metrics_instrumentation(otlp_endpoint: str | None = None) -> MeterProvider:
    """Idempotent - returns the existing MeterProvider if already set up,
    same pattern as otel_setup.setup_otel_instrumentation()."""
    global _meter_provider, _token_usage_histogram, _operation_duration_histogram

    if _meter_provider is not None:
        return _meter_provider

    import os
    endpoint = otlp_endpoint or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")

    resource = Resource.create({"service.name": "research-copilot-agent"})
    exporter = OTLPMetricExporter(endpoint=f"{endpoint}/v1/metrics")
    reader = PeriodicExportingMetricReader(exporter, export_interval_millis=5000)
    provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(provider)

    meter = metrics.get_meter("research_copilot.genai_metrics")

    _token_usage_histogram = meter.create_histogram(
        name="gen_ai.client.token.usage",
        unit="{token}",
        description="Number of tokens used per GenAI client operation",
    )
    _operation_duration_histogram = meter.create_histogram(
        name="gen_ai.client.operation.duration",
        unit="s",
        description="Duration of GenAI client operations",
    )

    _meter_provider = provider
    return _meter_provider


def _resolve_provider_name() -> str:
    """gen_ai.provider.name from OUR config, not response metadata -
    ChatDeepSeek's raw llm_output falsely reports \'openai\' since it uses
    an OpenAI-compatible wrapper internally. Verified via direct test."""
    return "groq" if settings.model_profile == "cheap" else "deepseek"


def _resolve_model_name() -> str:
    return settings.cheap_model_name if settings.model_profile == "cheap" else settings.primary_model_name


class GenAIMetricsCallbackHandler(BaseCallbackHandler):
    """Records gen_ai.client.token.usage and gen_ai.client.operation.duration
    for every chat-model call. Defensive: never raises - a metrics bug must
    never break the actual agent request."""

    def __init__(self) -> None:
        super().__init__()
        self._start_times: dict[UUID, float] = {}

    def on_chat_model_start(
        self, serialized: dict, messages: list, *, run_id: UUID, **kwargs: Any
    ) -> None:
        self._start_times[run_id] = time.monotonic()

    def on_llm_start(
        self, serialized: dict, prompts: list, *, run_id: UUID, **kwargs: Any
    ) -> None:
        self._start_times.setdefault(run_id, time.monotonic())

    def on_llm_end(self, response: Any, *, run_id: UUID, **kwargs: Any) -> None:
        try:
            if _token_usage_histogram is None or _operation_duration_histogram is None:
                return

            start = self._start_times.pop(run_id, None)
            duration_seconds = (time.monotonic() - start) if start is not None else None

            identity = _current_identity.get()
            provider_name = _resolve_provider_name()
            model_name = _resolve_model_name()

            base_attrs = {
                "gen_ai.operation.name": "chat",
                "gen_ai.provider.name": provider_name,
                "gen_ai.request.model": model_name,
            }
            if identity.session_id:
                base_attrs["session_id"] = identity.session_id

            if duration_seconds is not None:
                _operation_duration_histogram.record(duration_seconds, attributes=base_attrs)

            token_usage = None
            if getattr(response, "llm_output", None):
                token_usage = response.llm_output.get("token_usage")
            if token_usage is None and response.generations:
                gen = response.generations[0][0]
                msg = getattr(gen, "message", None)
                usage_metadata = getattr(msg, "usage_metadata", None) if msg else None
                if usage_metadata:
                    token_usage = {
                        "prompt_tokens": usage_metadata.get("input_tokens"),
                        "completion_tokens": usage_metadata.get("output_tokens"),
                    }

            if token_usage:
                input_tokens = token_usage.get("prompt_tokens")
                output_tokens = token_usage.get("completion_tokens")
                if input_tokens is not None:
                    _token_usage_histogram.record(
                        input_tokens, attributes={**base_attrs, "gen_ai.token.type": "input"}
                    )
                if output_tokens is not None:
                    _token_usage_histogram.record(
                        output_tokens, attributes={**base_attrs, "gen_ai.token.type": "output"}
                    )
        except Exception:
            # Never let a metrics-recording bug break the actual agent request.
            pass
