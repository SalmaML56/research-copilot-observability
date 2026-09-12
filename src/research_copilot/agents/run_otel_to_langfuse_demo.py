"""
Phase 3, step 26: send traces to Langfuse DIRECTLY over OTLP — bypassing
both our own Collector and Phase 2's LangChain CallbackHandler entirely.
Confirms Langfuse can be reached as a plain OTel backend, same as any
other OTel-compatible tool.

Endpoint/auth verified against Langfuse's own docs:
  - URL:  {LANGFUSE_HOST}/api/public/otel/v1/traces
  - Auth: HTTP Basic, base64("public_key:secret_key")

Run:
    uv run python -m research_copilot.agents.run_otel_to_langfuse_demo
"""

import base64
import os

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
langfuse_host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

auth = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()

resource = Resource.create({"service.name": "research-copilot-otlp-to-langfuse"})
provider = TracerProvider(resource=resource)
exporter = OTLPSpanExporter(
    endpoint=f"{langfuse_host}/api/public/otel/v1/traces",
    headers={"Authorization": f"Basic {auth}"},
)
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
    print("\nDone. Check cloud.langfuse.com -> Tracing for this trace (service.name:")
    print("research-copilot-otlp-to-langfuse). Compare its span tree structure")
    print("against a Phase 2 (CallbackHandler-based) trace from earlier.")
