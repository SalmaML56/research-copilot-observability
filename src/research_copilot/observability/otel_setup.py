"""
Phase 3, step 20: OpenInference auto-instrumentation for LangChain.
Idempotent — calling twice returns the same provider.
"""

import os

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from openinference.instrumentation.langchain import LangChainInstrumentor

from research_copilot.observability.identity import IdentitySpanProcessor

_provider = None


def setup_otel_instrumentation() -> TracerProvider:
    global _provider

    if _provider is not None:
        return _provider

    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    resource = Resource.create({"service.name": "research-copilot-agent"})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=f"{otlp_endpoint}/v1/traces")
    provider.add_span_processor(BatchSpanProcessor(exporter))
    provider.add_span_processor(IdentitySpanProcessor())
    trace.set_tracer_provider(provider)

    LangChainInstrumentor().instrument(tracer_provider=provider)

    _provider = provider
    return _provider
