"""
Phase 4, step 27: send traces to a self-hosted Arize Phoenix instance via
OpenInference + OTLP.

Run:
    docker compose up -d phoenix
    uv run python -m research_copilot.agents.run_phoenix_demo

Then open http://localhost:6006 to see the trace in Phoenix's UI.
"""

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from openinference.instrumentation.langchain import LangChainInstrumentor

resource = Resource.create({"service.name": "research-copilot-phoenix-demo"})
provider = TracerProvider(resource=resource)
exporter = OTLPSpanExporter(endpoint="http://localhost:6006/v1/traces")
provider.add_span_processor(BatchSpanProcessor(exporter))
trace.set_tracer_provider(provider)

LangChainInstrumentor().instrument(tracer_provider=provider)

from research_copilot.agents.main_agent import agent  # noqa: E402


if __name__ == "__main__":
    task = "Search the web briefly for what year the Eiffel Tower was built, and answer in one sentence."
    print(f"Task: {task}\n")

    result = agent.invoke({"messages": [{"role": "user", "content": task}]})

    print("=== Answer ===")
    print(result["messages"][-1].content)

    provider.force_flush()
    print("\nDone. Open http://localhost:6006 to see this trace in Phoenix's UI.")
