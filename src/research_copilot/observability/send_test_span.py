from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource

resource = Resource.create({"service.name": "research-copilot-phase0-check"})
provider = TracerProvider(resource=resource)
exporter = OTLPSpanExporter(endpoint="http://localhost:4318/v1/traces")
provider.add_span_processor(BatchSpanProcessor(exporter))
trace.set_tracer_provider(provider)

tracer = trace.get_tracer("phase0.smoke_test")

with tracer.start_as_current_span("test-span") as span:
    span.set_attribute("gen_ai.agent.name", "phase0-smoke-test")
    span.set_attribute("phase", "0")
    print("Span sent. Force-flushing exporter...")

provider.force_flush()
print("Done. Check `docker compose logs otel-collector` for the span dump.")
