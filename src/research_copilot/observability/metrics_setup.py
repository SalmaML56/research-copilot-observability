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

import os
import time
from pathlib import Path
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
_run_steps_histogram = None

# Phase 5, P5-43 (Step 36d): threads currently paused on a human approval.
# This is an in-process registry, not a query against the checkpoint DB -
# stated plainly because it means the gauge counts approvals pending in THIS
# uvicorn process. A restart resets it to 0 even though the threads are
# still paused on disk. Good enough for the alert (which is about a backlog
# building up in a running service), wrong for an audit.
_pending_approvals: set[str] = set()


def mark_pending_approval(thread_id: str) -> None:
    _pending_approvals.add(thread_id)


def clear_pending_approval(thread_id: str) -> None:
    _pending_approvals.discard(thread_id)


def _checkpoint_db_path() -> Path:
    """P5-30 fix: this used to be the bare relative string
    "checkpoints.sqlite", so the gauge silently read 0 whenever the process
    was started from any directory other than the repo root - which is the
    normal case for uvicorn under a process manager."""
    configured = os.getenv("CHECKPOINT_DB_PATH")
    if configured:
        return Path(configured).expanduser().resolve()
    # repo root = .../src/research_copilot/observability/metrics_setup.py
    return (Path(__file__).resolve().parents[3] / "checkpoints.sqlite").resolve()


def setup_metrics_instrumentation(otlp_endpoint: str | None = None) -> MeterProvider:
    """Idempotent - returns the existing MeterProvider if already set up,
    same pattern as otel_setup.setup_otel_instrumentation()."""
    global _meter_provider, _token_usage_histogram, _operation_duration_histogram
    global _run_steps_histogram

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

    # --- Phase 5, Step 35 custom metrics ---
    # These do not come for free from auto-instrumentation or from the
    # Collector's spanmetrics connector: nothing upstream knows what a
    # "planning step", a "checkpoint database" or a "pending approval" is.
    _run_steps_histogram = meter.create_histogram(
        name="research_copilot.run.steps",
        # Unit is an annotation, not "1": the OTLP->Prometheus translation
        # turns unit "1" into a "_ratio" name suffix, which is wrong for a
        # count of planning steps. Verified against the live metric names.
        unit="{step}",
        description="Number of planning steps (todo items) in a single agent run",
    )

    def _observe_checkpoint_db_size(options):
        path = _checkpoint_db_path()
        size = path.stat().st_size if path.exists() else 0
        yield metrics.Observation(size, {"db.path": str(path)})

    meter.create_observable_gauge(
        name="research_copilot.checkpoint.db_size_bytes",
        unit="By",
        description="Size of the SQLite checkpoint database on disk",
        callbacks=[_observe_checkpoint_db_size],
    )

    def _observe_pending_approvals(options):
        yield metrics.Observation(len(_pending_approvals), {})

    meter.create_observable_gauge(
        name="research_copilot.runs.pending_approval",
        # Same reason as above: unit "1" produced
        # research_copilot_runs_pending_approval_ratio in Prometheus.
        unit="{run}",
        description="Runs currently paused waiting for a human approval decision",
        callbacks=[_observe_pending_approvals],
    )

    _meter_provider = provider
    return _meter_provider


def record_run_steps(step_count: int) -> None:
    """Defensive by the same rule as the callback handler: a metrics bug
    must never break a real agent request."""
    try:
        if _run_steps_histogram is not None:
            _run_steps_histogram.record(
                step_count,
                attributes={
                    "gen_ai.request.model": _resolve_model_name(),
                    "gen_ai.provider.name": _resolve_provider_name(),
                },
            )
    except Exception:
        pass


def flush_metrics() -> None:
    """Force an export now instead of waiting out the 5s interval. Used by
    short-lived CLI entrypoints that would otherwise exit first."""
    try:
        if _meter_provider is not None:
            _meter_provider.force_flush()
    except Exception:
        pass


def _resolve_provider_name() -> str:
    """gen_ai.provider.name from OUR config, not response metadata -
    ChatDeepSeek's raw llm_output falsely reports \'openai\' since it uses
    an OpenAI-compatible wrapper internally. Verified via direct test."""
    return "groq" if settings.model_profile == "cheap" else "deepseek"


def _resolve_model_name(response: Any = None) -> str:
    """Prefer the model name the PROVIDER reported over the one we requested.

    Verified live: .env requests "deepseek-chat" but the model span carries
    gen_ai.request.model = "deepseek-flash" (a provider-side alias). The
    Collector's cost transform keys on the span value, so if this metric
    reported the configured name instead, a panel joining cost (by span
    model) to tokens (by metric model) would silently match nothing.
    """
    if response is not None:
        llm_output = getattr(response, "llm_output", None) or {}
        reported = llm_output.get("model_name") or llm_output.get("model")
        if reported:
            return str(reported)
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
            model_name = _resolve_model_name(response)

            base_attrs = {
                "gen_ai.operation.name": "chat",
                "gen_ai.provider.name": provider_name,
                "gen_ai.request.model": model_name,
            }
            # Cardinality note (P5-13): session_id is deliberately a label
            # HERE but deliberately NOT a spanmetrics dimension. Step 35 asks
            # for "tokens and cost per session", which needs the label, and
            # these two histograms only get one datapoint per model call -
            # bounded by traffic, not by span volume. Putting it on the
            # Collector's spanmetrics instead would have multiplied every
            # RED series by every session ever seen.
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
