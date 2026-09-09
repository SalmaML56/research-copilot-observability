"""
Phase 3, step 22: OpenLLMetry (Traceloop's opentelemetry-instrumentation-
langchain) instrumentation, run separately from OpenInference so span
trees can be compared without the two instrumentors double-wrapping the
same LangChain calls in one process.

IMPORTANT: do not import/run this in the same process as
run_otel_demo.py (OpenInference) — both patch LangChain's internals.
Compare by running each script separately and comparing Collector logs.

Run:
    docker compose up -d
    uv run python -m research_copilot.agents.run_openllmetry_demo
    docker compose logs otel-collector | tail -60
"""

import os

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.instrumentation.langchain import LangchainInstrumentor

otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
resource = Resource.create({"service.name": "research-copilot-agent-openllmetry"})
provider = TracerProvider(resource=resource)
exporter = OTLPSpanExporter(endpoint=f"{otlp_endpoint}/v1/traces")
provider.add_span_processor(BatchSpanProcessor(exporter))
trace.set_tracer_provider(provider)

LangchainInstrumentor().instrument(tracer_provider=provider)

from research_copilot.agents.main_agent import agent  # noqa: E402


if __name__ == "__main__":
    task = "What is a small modular nuclear reactor? Answer in 2 short sentences, no research needed."
    print(f"Task: {task}\n")

    result = agent.invoke({"messages": [{"role": "user", "content": task}]})

    print("=== Answer ===")
    print(result["messages"][-1].content)
    print("\nCheck `docker compose logs otel-collector` for OpenLLMetry spans.")
    print("Compare against run_otel_demo.py's (OpenInference) span tree.")
