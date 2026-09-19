"""
Phase 3, step 26: send traces to Langfuse DIRECTLY over OTLP — bypassing
both our own Collector and Phase 2's LangChain CallbackHandler entirely.
Confirms Langfuse can be reached as a plain OTel backend, same as any
other OTel-compatible tool.

Endpoint/auth verified against Langfuse's own docs:
  - URL:  {LANGFUSE_HOST}/api/public/otel/v1/traces
  - Auth: HTTP Basic, base64("public_key:secret_key")

Step 26 comparison (this run = the "direct OTel" path): compare against
main_agent.py's CallbackHandler-based path (Phase 2) on identity metadata,
delegation, tools, and model calls. Both paths are run in SEPARATE
processes since callbacks and OTel instrumentation touch overlapping
internals - do not import/run together.

Run:
    uv run python -m research_copilot.agents.run_otel_to_langfuse_demo
"""

import base64
import os
import time
import uuid

from dotenv import load_dotenv
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from openinference.instrumentation.langchain import LangChainInstrumentor

load_dotenv()

from research_copilot.observability.identity import IdentitySpanProcessor, set_identity, reset_identity  # noqa: E402

public_key = os.environ["LANGFUSE_PUBLIC_KEY"]
secret_key = os.environ["LANGFUSE_SECRET_KEY"]
langfuse_host = os.getenv("LANGFUSE_HOST", "http://localhost:3000")

auth = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()

resource = Resource.create({"service.name": "research-copilot-otlp-to-langfuse"})
provider = TracerProvider(resource=resource)
exporter = OTLPSpanExporter(
    endpoint=f"{langfuse_host}/api/public/otel/v1/traces",
    headers={"Authorization": f"Basic {auth}"},
)
provider.add_span_processor(BatchSpanProcessor(exporter))
provider.add_span_processor(IdentitySpanProcessor())
trace.set_tracer_provider(provider)

LangChainInstrumentor().instrument(tracer_provider=provider)

from research_copilot.agents.main_agent import agent  # noqa: E402


if __name__ == "__main__":
    session_id = f"step26-direct-otel-{uuid.uuid4().hex[:6]}"
    task = "Research the CAP theorem in distributed systems and write a short summary."
    print(f"Task: {task}")
    print(f"Session ID (for verification): {session_id}\n")

    token = set_identity(session_id=session_id, user_id="step26-direct-otel-user", environment="dev")
    try:
        result = agent.invoke({"messages": [{"role": "user", "content": task}]})
    finally:
        reset_identity(token)

    print("=== Answer ===")
    print(result["messages"][-1].content[:200])

    provider.force_flush()
    time.sleep(3)

    print(f"\nDone. Sent to Langfuse at: {langfuse_host}")
    print(f"Session ID for comparison: {session_id}")
