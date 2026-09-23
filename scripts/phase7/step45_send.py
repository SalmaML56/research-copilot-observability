"""Step 45 verification, phase 1: send fake PII through the collector.

    uv run python scripts/phase7/step45_send.py <label> <manifest.json> [--real]

Always: one synthetic span (attribute + span event) and one OTLP log record
(body + attribute) carrying the fake PII, straight to the collector.
--real: also one real POST /research on the app (:8000) whose topic and
user_id carry it. That's a full DeepSeek run up to the approval pause.

Sessions are picked so trace.session_sampled is true, so tail sampling
keeps them. Check with step45_check.py after decision_wait (5 min).
"""

import json
import sys
import time
import uuid

import httpx
from opentelemetry._logs import SeverityNumber
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import SimpleLogRecordProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

from research_copilot.observability.identity import session_sampled

# All fake. 555-01xx is the reserved fictional NANP range; example.com is
# reserved; the keys are made-up strings in the right shape.
PII = {
    "email": "jane.doe.step45@example.com",
    "phone_us": "+1 415-555-0133",
    "phone_intl": "+44 20 7946 0958",
    "sk_key": "sk-step45FAKEabcdefghijklmnop1234",
    "groq_key": "gsk_step45FAKEabcdefghijklmnopqrst",
    "bearer": "Bearer step45FAKEtokenABCDEFGH12345",
}
TEXT = (
    f"Contact {PII['email']} or call {PII['phone_us']} / {PII['phone_intl']}. "
    f"Keys: {PII['sk_key']} {PII['groq_key']}. Header: {PII['bearer']}. "
    "Control, must survive: the reactor produced 1200 MW in 2023, see page 415."
)

label, out = sys.argv[1], sys.argv[2]
real = "--real" in sys.argv


def sampled_session(prefix: str) -> str:
    while True:
        sid = f"{prefix}-{uuid.uuid4()}"
        if session_sampled(sid):
            return sid


manifest = {"label": label, "pii": PII, "text": TEXT, "started": time.time()}

resource = Resource.create({"service.name": "step45-fake-pii"})
tp = TracerProvider(resource=resource)
tp.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter(endpoint="http://localhost:4318/v1/traces")))
lp = LoggerProvider(resource=resource)
lp.add_log_record_processor(SimpleLogRecordProcessor(OTLPLogExporter(endpoint="http://localhost:4318/v1/logs")))

sid = sampled_session(f"s45-{label}-synthetic")
with tp.get_tracer("step45").start_as_current_span("step45-pii-span") as span:
    span.set_attribute("session_id", sid)
    span.set_attribute("trace.session_sampled", True)
    span.set_attribute("user_id", PII["email"])
    span.set_attribute("input.value", TEXT)
    span.set_attribute("http.request.header.authorization", PII["bearer"])
    span.add_event("pii-event", {"detail": TEXT})
    trace_id = format(span.get_span_context().trace_id, "032x")
lp.get_logger("step45").emit(
    timestamp=time.time_ns(), severity_number=SeverityNumber.INFO, severity_text="INFO",
    body=f"step45 {label} log body: {TEXT}", attributes={"session_id": sid, "topic": TEXT},
)
tp.shutdown()
lp.shutdown()
manifest["synthetic"] = {"session_id": sid, "trace_id": trace_id}

if real:
    rsid = sampled_session(f"s45-{label}-real")
    manifest["real"] = {"session_id": rsid, "sent": time.time()}
    r = httpx.post(
        "http://localhost:8000/research",
        json={"topic": f"In two sentences, what is a tokamak? {TEXT}", "thread_id": rsid, "user_id": PII["email"]},
        timeout=1800,
    )
    manifest["real"].update({"http": r.status_code, "body": r.json() if r.status_code == 200 else r.text[:300]})

manifest["finished"] = time.time()
json.dump(manifest, open(out, "w"), indent=1)
print(json.dumps({k: v for k, v in manifest.items() if k in ("synthetic", "real")}, indent=1))
