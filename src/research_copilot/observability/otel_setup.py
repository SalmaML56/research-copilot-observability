"""
Phase 3, step 20: OpenInference auto-instrumentation for LangChain.
Idempotent — calling twice returns the same provider.
"""

import os

from dotenv import load_dotenv
from opentelemetry import trace
from opentelemetry.sdk.trace import SpanLimits, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from openinference.instrumentation.langchain import LangChainInstrumentor

from research_copilot.observability.identity import IdentitySpanProcessor

_provider = None

# Review v2, Addendum C: the SDK default is 128 attributes per span.
# OpenInference flattens every chat message into several attributes, so
# long-context ChatDeepSeek spans overflow that limit. On overflow the SDK
# evicts the OLDEST attributes first, and IdentitySpanProcessor.on_start
# writes first - so session_id/user_id/prompt_version/environment were the
# first things thrown away, on exactly the biggest and most expensive model
# calls. Measured: 10 of 349 spans in a real trace had lost all four, and
# every one of them had droppedAttributesCount > 0.
DEFAULT_SPAN_ATTRIBUTE_LIMIT = 2048


def setup_otel_instrumentation() -> TracerProvider:
    global _provider

    if _provider is not None:
        return _provider

    # Review v2, Step 21: load .env here too. Entrypoints that import this
    # module without calling load_dotenv() themselves would otherwise read a
    # stale/absent OTEL_EXPORTER_OTLP_ENDPOINT.
    load_dotenv()

    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    attribute_limit = int(
        os.getenv("OTEL_SPAN_ATTRIBUTE_COUNT_LIMIT", str(DEFAULT_SPAN_ATTRIBUTE_LIMIT))
    )
    resource = Resource.create({"service.name": "research-copilot-agent"})
    provider = TracerProvider(
        resource=resource,
        span_limits=SpanLimits(max_span_attributes=attribute_limit),
    )
    exporter = OTLPSpanExporter(endpoint=f"{otlp_endpoint}/v1/traces")
    provider.add_span_processor(BatchSpanProcessor(exporter))
    provider.add_span_processor(IdentitySpanProcessor())
    trace.set_tracer_provider(provider)

    LangChainInstrumentor().instrument(tracer_provider=provider)

    _provider = provider
    return _provider
