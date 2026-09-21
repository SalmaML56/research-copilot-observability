"""
Phase 5, P5-02 (review v2, Step 17 / Addendum D): one switch that decides
which tracing backend the process feeds.

The problem this fixes, measured on a real trace: `tools.py` carried a
bare `@observe(as_type="tool")` on every tool. Langfuse v4 implements
`@observe` on top of OpenTelemetry and attaches its own span processor to
the global TracerProvider, so every tool call was recorded twice - once by
OpenInference, once by Langfuse - and BOTH copies were exported to the
Collector. Counted in Tempo: 74 spans named `web_search` for 37 real
`web_search.ddgs_http_call` spans, plus 224 stray `langfuse.*` attributes.

Any Phase 5 panel or alert counting tool calls, tool errors, or tool
latency would therefore have been exactly 2x wrong.

TRACING_BACKEND values:
  otel      (default) OpenInference/OTel only. `@observe` becomes a no-op
            and the Langfuse client is never constructed, so nothing
            attaches a second span processor.
  langfuse  Langfuse decorators active. Use for the Phase 2 demos.
  both      Both active. Accepts the double-counting; only useful when
            deliberately comparing the two pipelines (Steps 26, 28).
"""

import os

from dotenv import load_dotenv

load_dotenv()

VALID_TRACING_BACKENDS = ("otel", "langfuse", "both")
_LANGFUSE_BACKENDS = ("langfuse", "both")


def get_tracing_backend() -> str:
    value = os.getenv("TRACING_BACKEND", "otel").strip().lower()
    if value not in VALID_TRACING_BACKENDS:
        raise RuntimeError(
            f"TRACING_BACKEND={value!r} is not valid. "
            f"Must be one of {VALID_TRACING_BACKENDS}."
        )
    return value


def langfuse_enabled() -> bool:
    return get_tracing_backend() in _LANGFUSE_BACKENDS


def observe_if_langfuse(**observe_kwargs):
    """Applies Langfuse's `@observe` only when the Langfuse backend is on.

    The `langfuse` import is deliberately deferred into the enabled branch:
    importing it and letting it build a client is what attaches the second
    span processor in the first place.
    """

    def decorator(func):
        if not langfuse_enabled():
            return func
        from langfuse import observe

        return observe(**observe_kwargs)(func)

    return decorator


def update_langfuse_span(**kwargs) -> None:
    """No-op unless the Langfuse backend is on. Never raises."""
    if not langfuse_enabled():
        return
    try:
        from langfuse import get_client

        get_client().update_current_span(**kwargs)
    except Exception:
        pass
