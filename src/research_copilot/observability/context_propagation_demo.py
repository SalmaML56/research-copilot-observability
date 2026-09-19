"""
Phase 3, step 25: deliberately break trace context propagation, observe
the resulting split trace, then fix it — exercised against the REAL
researcher subagent graph (with a stub model, no real API calls), not
synthetic spans, per review feedback that the original version used plain
tracer.start_as_current_span() calls instead of a real subagent.

The problem: Python's threading.Thread does NOT automatically carry OTel
trace context into the new thread — context lives in contextvars, and raw
threads start with a FRESH, empty context unless explicitly copied over.
This means a subagent (or any work) run inside a plain threading.Thread
without care will start its own, disconnected trace instead of continuing
the parent trace.

Correction (review feedback): asyncio.create_task does NOT have this
problem and never did — since Python 3.7, asyncio automatically copies
the current contextvars.Context into every new Task (this is how asyncio
integrates with contextvars, confirmed in the asyncio/contextvars docs
and unrelated to the 3.11 version specifically). The propagation gap
described above is specific to threading.Thread (and any other mechanism
that hands work to a new OS thread), not to asyncio tasks.

Run:
    docker compose up -d otel-collector
    uv run python -m research_copilot.observability.context_propagation_demo
    docker compose logs otel-collector | grep "Trace ID"
"""

import os
import threading

from dotenv import load_dotenv
from opentelemetry import context, trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from openinference.instrumentation.langchain import LangChainInstrumentor

load_dotenv()  # Step 21: must load .env before reading OTEL_EXPORTER_OTLP_ENDPOINT below

otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
resource = Resource.create({"service.name": "research-copilot-context-demo"})
provider = TracerProvider(resource=resource)
exporter = OTLPSpanExporter(endpoint=f"{otlp_endpoint}/v1/traces")
provider.add_span_processor(BatchSpanProcessor(exporter))
trace.set_tracer_provider(provider)

LangChainInstrumentor().instrument(tracer_provider=provider)

tracer = trace.get_tracer("research_copilot.context_demo")


def get_trace_id() -> str:
    span = trace.get_current_span()
    return format(span.get_span_context().trace_id, "032x")


def _build_stub_agent():
    """
    Builds the REAL deep agent graph (real researcher subagent, real
    LangGraph/deepagents middleware) with a stub model so this demo makes
    zero real API calls, per review feedback ("fake/stub model OK for
    this check") — the goal is testing trace-context mechanics through
    the actual subagent graph shape, not model quality.
    """
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import AIMessage
    from deepagents import create_deep_agent

    from research_copilot.agents.subagents import researcher

    class StubChatModel(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    fake_model = StubChatModel(responses=[
        AIMessage(
            content="",
            tool_calls=[{"name": "task", "args": {"description": "Say hello", "subagent_type": "researcher"}, "id": "call_1"}],
        ),
        AIMessage(content="Stub researcher response: hello."),
        AIMessage(content="Done. Lead agent final answer."),
    ])

    return create_deep_agent(model=fake_model, tools=[], subagents=[researcher])


def run_broken_demo():
    print("=== BROKEN: real researcher subagent invoked in a plain threading.Thread ===")
    agent = _build_stub_agent()
    result_holder = {}

    def child_work():
        with tracer.start_as_current_span("broken.subagent_thread"):
            result = agent.invoke({"messages": [{"role": "user", "content": "test"}]})
            result_holder["trace_id"] = get_trace_id()
            result_holder["answer"] = result["messages"][-1].content

    with tracer.start_as_current_span("broken.parent_span"):
        parent_trace_id = get_trace_id()
        print(f"  [main thread]    parent trace_id: {parent_trace_id}")

        t = threading.Thread(target=child_work)
        t.start()
        t.join()

    print(f"  [broken thread]  child trace_id:  {result_holder['trace_id']}")
    print(f"  Answer captured: {result_holder['answer']!r}")
    print()


def run_fixed_demo():
    print("=== FIXED: context explicitly captured and attached before invoking the real subagent graph ===")
    agent = _build_stub_agent()
    result_holder = {}

    def child_work(captured_context):
        token = context.attach(captured_context)
        try:
            with tracer.start_as_current_span("fixed.subagent_thread"):
                result = agent.invoke({"messages": [{"role": "user", "content": "test"}]})
                result_holder["trace_id"] = get_trace_id()
                result_holder["answer"] = result["messages"][-1].content
        finally:
            context.detach(token)

    with tracer.start_as_current_span("fixed.parent_span"):
        parent_trace_id = get_trace_id()
        print(f"  [main thread]    parent trace_id: {parent_trace_id}")

        captured = context.get_current()
        t = threading.Thread(target=child_work, args=(captured,))
        t.start()
        t.join()

    print(f"  [fixed thread]   child trace_id:  {result_holder['trace_id']}")
    print(f"  Answer captured: {result_holder['answer']!r}")
    print()


if __name__ == "__main__":
    run_broken_demo()
    run_fixed_demo()

    provider.force_flush()
    print("Done. Check the Collector logs — compare the two scenarios above:")
    print("  'broken' parent/child trace_ids will DIFFER (split trace).")
    print("  'fixed' parent/child trace_ids will MATCH (single connected trace).")
    print("Both scenarios exercise the REAL researcher subagent graph (stub model, no API calls).")
