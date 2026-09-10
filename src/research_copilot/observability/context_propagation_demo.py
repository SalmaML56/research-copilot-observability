"""
Phase 3, step 25: deliberately break trace context propagation, observe
the resulting split trace, then fix it.

The problem: Python's threading.Thread does NOT automatically carry OTel
trace context into the new thread — context lives in contextvars, and raw
threads start with a FRESH, empty context unless explicitly copied over.
This means a subagent (or any work) run inside a plain threading.Thread
or asyncio.create_task without care will start its own, disconnected
trace instead of continuing the parent trace.

Run:
    docker compose up -d
    uv run python -m research_copilot.observability.context_propagation_demo
    docker compose logs otel-collector | grep "Trace ID"
"""

import threading
import os

from opentelemetry import context, trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource

otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
resource = Resource.create({"service.name": "research-copilot-context-demo"})
provider = TracerProvider(resource=resource)
exporter = OTLPSpanExporter(endpoint=f"{otlp_endpoint}/v1/traces")
provider.add_span_processor(BatchSpanProcessor(exporter))
trace.set_tracer_provider(provider)

tracer = trace.get_tracer("research_copilot.context_demo")


def get_trace_id() -> str:
    span = trace.get_current_span()
    return format(span.get_span_context().trace_id, "032x")


def broken_child_work():
    with tracer.start_as_current_span("broken.child_span") as span:
        child_trace_id = get_trace_id()
        span.set_attribute("demo.scenario", "broken")
        print(f"  [broken thread]  child trace_id:  {child_trace_id}")


def run_broken_demo():
    print("=== BROKEN: subagent runs in a plain threading.Thread ===")
    with tracer.start_as_current_span("broken.parent_span"):
        parent_trace_id = get_trace_id()
        print(f"  [main thread]    parent trace_id: {parent_trace_id}")

        t = threading.Thread(target=broken_child_work)
        t.start()
        t.join()
    print()


def fixed_child_work(captured_context):
    token = context.attach(captured_context)
    try:
        with tracer.start_as_current_span("fixed.child_span") as span:
            child_trace_id = get_trace_id()
            span.set_attribute("demo.scenario", "fixed")
            print(f"  [fixed thread]   child trace_id:  {child_trace_id}")
    finally:
        context.detach(token)


def run_fixed_demo():
    print("=== FIXED: context explicitly captured and attached in the new thread ===")
    with tracer.start_as_current_span("fixed.parent_span"):
        parent_trace_id = get_trace_id()
        print(f"  [main thread]    parent trace_id: {parent_trace_id}")

        captured = context.get_current()
        t = threading.Thread(target=fixed_child_work, args=(captured,))
        t.start()
        t.join()
    print()


if __name__ == "__main__":
    run_broken_demo()
    run_fixed_demo()

    provider.force_flush()
    print("Done. Check the Collector logs — compare the two scenarios above:")
    print("  'broken' parent/child trace_ids will DIFFER (split trace).")
    print("  'fixed' parent/child trace_ids will MATCH (single connected trace).")
