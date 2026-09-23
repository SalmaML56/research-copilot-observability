"""Step 44 verification, phase 1: generate traffic and write a manifest.

- N normal runs: POST /research/{uuid}/approve on the real app (:8000). The
  thread doesn't exist, so it returns 400 without touching the model - a
  real app trace with session_id + trace.session_sampled, status UNSET.
- 1 error run: POST /research on an app instance started with an invalid
  DEEPSEEK_API_KEY (:8001), with a session the session policy would DROP.
- 2 fake model-call spans sent straight to the collector: cost_usd 0.02
  (must be kept) and 0.005 (control, must be dropped), both on sessions the
  session policy would drop.
"""

import json
import sys
import time
import uuid

import httpx
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

from research_copilot.observability.identity import session_sampled

N = int(sys.argv[1])
out = sys.argv[2]


def unsampled_session(prefix: str) -> str:
    while True:
        sid = f"{prefix}-{uuid.uuid4()}"
        if not session_sampled(sid):
            return sid


manifest = {"started": time.time(), "normal": [], "error": None, "fake": {}}

with httpx.Client(timeout=120) as client:
    for _ in range(N):
        sid = f"s44-normal-{uuid.uuid4()}"
        r = client.post(f"http://localhost:8000/research/{sid}/approve")
        manifest["normal"].append({"session_id": sid, "http": r.status_code, "predicted_kept": session_sampled(sid)})

    err_sid = unsampled_session("s44-error")
    r = client.post("http://localhost:8001/research", json={"topic": "step 44 error check", "thread_id": err_sid})
    manifest["error"] = {"session_id": err_sid, "http": r.status_code, "body": r.text[:200]}

provider = TracerProvider(resource=Resource.create({"service.name": "step44-fake-span"}))
provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter(endpoint="http://localhost:4318/v1/traces")))
tracer = provider.get_tracer("step44")
for label, cost in (("expensive", 0.02), ("cheap_control", 0.005)):
    sid = unsampled_session(f"s44-{label}")
    with tracer.start_as_current_span("ChatDeepSeek") as span:
        span.set_attribute("session_id", sid)
        span.set_attribute("trace.session_sampled", False)
        span.set_attribute("gen_ai.operation.name", "chat")
        span.set_attribute("gen_ai.usage.cost_usd", cost)
        trace_id = format(span.get_span_context().trace_id, "032x")
    manifest["fake"][label] = {"session_id": sid, "cost_usd": cost, "trace_id": trace_id}
provider.shutdown()

manifest["finished"] = time.time()
json.dump(manifest, open(out, "w"), indent=1)
kept = sum(n["predicted_kept"] for n in manifest["normal"])
print(f"normal: {N} sent, http codes {sorted({n['http'] for n in manifest['normal']})}, predicted kept {kept}")
print("error:", manifest["error"])
print("fake:", manifest["fake"])
