"""
Phase 5, step 37 (P5-50 / P5-51): structured JSON logs carrying trace_id.

Before this module the codebase had no `logging` usage at all - every
diagnostic was a bare `print()`, which means it went to the terminal and
nowhere else. Nothing correlated a log line with the trace that produced it.

Two things happen here:

1. A JSON formatter that injects the *current* OTel span context into every
   record, so a log line emitted anywhere inside a request already knows its
   trace. The IDs are formatted as the 32-hex / 16-hex lowercase strings
   Tempo and Loki expect - `format(ctx.trace_id, "032x")`, not the raw int.
   Emitting the int is the usual reason trace-to-log correlation silently
   fails: Grafana's derived field matches, finds no such trace, and the link
   dead-ends.

2. An OTLP log exporter, so the same records reach Loki through the
   Collector's logs pipeline. The Grafana LGTM image already provisions both
   directions of the link (Tempo's `tracesToLogsV2`, and Loki's `trace_id`
   derived field pointing back at Tempo) - they just never had any logs to
   operate on.
"""

import json
import logging
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from opentelemetry import trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource

from research_copilot.observability.identity import _current_identity

SERVICE_NAME = "research-copilot-agent"

_logger_provider: LoggerProvider | None = None
_configured = False

# Attributes already carried explicitly in the JSON payload; re-emitting the
# whole LogRecord __dict__ would bury them in stdlib noise.
_RESERVED = {
    "args", "asctime", "created", "exc_info", "exc_text", "filename",
    "funcName", "levelname", "levelno", "lineno", "module", "msecs",
    "message", "msg", "name", "pathname", "process", "processName",
    "relativeCreated", "stack_info", "thread", "threadName", "taskName",
    # Injected by IdentityFilter and emitted explicitly in the payload.
    "session_id", "user_id", "environment", "prompt_version",
}


class IdentityFilter(logging.Filter):
    """Copies request identity onto the LogRecord.

    The JSON formatter below reads identity directly, but the OTLP path does
    not go through a formatter at all - LoggingHandler maps the record's
    extra attributes to OTel log attributes, which Loki then indexes. Without
    this filter, Loki logs carry trace_id (the SDK sets that natively) but
    are not searchable by session_id or user_id, which is exactly the query
    an on-call person makes first.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        identity = _current_identity.get()
        if identity.session_id and not hasattr(record, "session_id"):
            record.session_id = identity.session_id
        if identity.user_id and not hasattr(record, "user_id"):
            record.user_id = identity.user_id
        if not hasattr(record, "environment"):
            record.environment = identity.environment
        if not hasattr(record, "prompt_version"):
            record.prompt_version = identity.prompt_version
        return True


class TraceContextJSONFormatter(logging.Formatter):
    """Renders one JSON object per line, with trace and identity context."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service.name": SERVICE_NAME,
        }

        span_context = trace.get_current_span().get_span_context()
        if span_context.is_valid:
            # 32/16 lowercase hex - the wire format Tempo and Loki index on.
            payload["trace_id"] = format(span_context.trace_id, "032x")
            payload["span_id"] = format(span_context.span_id, "016x")
            payload["trace_flags"] = format(span_context.trace_flags, "02x")

        identity = _current_identity.get()
        if identity.session_id:
            payload["session_id"] = identity.session_id
        if identity.user_id:
            payload["user_id"] = identity.user_id
        payload["environment"] = identity.environment
        payload["prompt_version"] = identity.prompt_version

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                try:
                    json.dumps(value)
                except (TypeError, ValueError):
                    value = repr(value)
                payload[key] = value

        return json.dumps(payload, default=str)


def setup_logging(level: int | None = None) -> logging.Logger:
    """Idempotent, same contract as setup_otel_instrumentation()."""
    global _logger_provider, _configured

    if _configured:
        return logging.getLogger("research_copilot")

    load_dotenv()
    resolved_level = level if level is not None else getattr(
        logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO
    )
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")

    root = logging.getLogger()
    root.setLevel(resolved_level)

    identity_filter = IdentityFilter()

    console = logging.StreamHandler()
    console.setFormatter(TraceContextJSONFormatter())
    console.addFilter(identity_filter)
    root.addHandler(console)

    # OTLP side: same records, shipped to the Collector's logs pipeline and
    # on to Loki. Failures here must not take the app down, so a broken or
    # absent Collector degrades to console-only logging.
    try:
        _logger_provider = LoggerProvider(
            resource=Resource.create({"service.name": SERVICE_NAME})
        )
        _logger_provider.add_log_record_processor(
            BatchLogRecordProcessor(
                OTLPLogExporter(endpoint=f"{endpoint}/v1/logs")
            )
        )
        set_logger_provider(_logger_provider)
        otlp_handler = LoggingHandler(
            level=resolved_level, logger_provider=_logger_provider
        )
        otlp_handler.addFilter(identity_filter)
        root.addHandler(otlp_handler)
    except Exception:
        logging.getLogger("research_copilot").warning(
            "OTLP log export unavailable; continuing with console logging only",
            exc_info=True,
        )

    # uvicorn installs its own handlers; route them through ours so HTTP
    # access lines are JSON and carry trace_id too.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True

    _configured = True
    return logging.getLogger("research_copilot")


def flush_logs() -> None:
    try:
        if _logger_provider is not None:
            _logger_provider.force_flush()
    except Exception:
        pass
