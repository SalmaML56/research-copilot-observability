"""
Phase 3, step 20: OpenInference auto-instrumentation for LangChain.

This replaces manual span creation with automatic conversion: once
LangChainInstrumentor().instrument() is called, every LangChain/LangGraph
call our agent makes is automatically turned into a standard
OpenTelemetry span — no code changes needed inside main_agent.py,
subagents.py, or tools.py themselves.

This is DIFFERENT from Phase 2's Langfuse CallbackHandler. OpenInference
produces vendor-neutral OTel spans that any OTel-compatible backend (our
Collector, Phoenix, Grafana/Tempo) can receive — not just Langfuse.
"""

import os

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from openinference.instrumentation.langchain import LangChainInstrumentor

_instrumented = False


def setup_otel_instrumentation() -> TracerProvider:
    """
    Sets up an OTel TracerProvider pointed at our Collector, and
    instruments LangChain so all agent activity is automatically traced.
    Safe to call more than once — only instruments on the first call.
    """
    global _instrumented

    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")

    resource = Resource.create({"service.name": "research-copilot-agent"})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=f"{otlp_endpoint}/v1/traces")
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    if not _instrumented:
        LangChainInstrumentor().instrument(tracer_provider=provider)
        _instrumented = True

    return provider
