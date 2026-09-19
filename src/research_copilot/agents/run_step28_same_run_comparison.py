"""
Phase 4, step 28: export ONE single agent invocation to BOTH Langfuse and
Phoenix SIMULTANEOUSLY, via two span processors on the same TracerProvider.
This guarantees an identical trace ID at both destinations (literally the
same OTel spans, exported twice), unlike two separate demo runs of the
same prompt which cannot guarantee identical execution.

Run:
    docker compose up -d phoenix
    (self-hosted Langfuse services must also be up)
    uv run python -m research_copilot.agents.run_step28_same_run_comparison
"""

import base64
import os
import time

from dotenv import load_dotenv
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from openinference.instrumentation.langchain import LangChainInstrumentor

load_dotenv()

public_key = os.environ["LANGFUSE_PUBLIC_KEY"]
secret_key = os.environ["LANGFUSE_SECRET_KEY"]
langfuse_host = os.getenv("LANGFUSE_HOST", "http://localhost:3000")
auth = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()

resource = Resource.create({"service.name": "research-copilot-step28-same-run"})
provider = TracerProvider(resource=resource)

phoenix_exporter = OTLPSpanExporter(endpoint="http://localhost:6006/v1/traces")
langfuse_exporter = OTLPSpanExporter(
    endpoint=f"{langfuse_host}/api/public/otel/v1/traces",
    headers={"Authorization": f"Basic {auth}"},
)

provider.add_span_processor(BatchSpanProcessor(phoenix_exporter))
provider.add_span_processor(BatchSpanProcessor(langfuse_exporter))
trace.set_tracer_provider(provider)

LangChainInstrumentor().instrument(tracer_provider=provider)

from research_copilot.agents.main_agent import agent  # noqa: E402


def get_current_trace_id() -> str:
    span = trace.get_current_span()
    return format(span.get_span_context().trace_id, "032x")


if __name__ == "__main__":
    tracer = trace.get_tracer("research_copilot.step28")
    task = "What is a small modular nuclear reactor? Answer in 2 sentences, no research needed."
    print(f"Task: {task}")

    with tracer.start_as_current_span("step28.same_run_root"):
        trace_id = get_current_trace_id()
        print(f"Trace ID (sent to BOTH Phoenix and Langfuse): {trace_id}\n")

        result = agent.invoke({"messages": [{"role": "user", "content": task}]})

    print("=== Answer ===")
    print(result["messages"][-1].content[:200])

    provider.force_flush()
    time.sleep(3)

    print(f"\nDone. Trace ID for verification: {trace_id}")
    print("Check this SAME trace ID in both:")
    print("  - Phoenix: http://localhost:6006")
    print(f"  - Langfuse: {langfuse_host}")
