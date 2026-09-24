"""
Fixes the identity-propagation gap (Steps 5, 15, 16, 24, 26, 30): 0 of 71
captured spans had session_id/user_id/prompt_version/environment.
"""

import contextvars
import hashlib
import os
from dataclasses import dataclass

from opentelemetry.sdk.trace import SpanProcessor


@dataclass
class RequestIdentity:
    session_id: str | None = None
    user_id: str | None = None
    prompt_version: str = "unknown"
    environment: str = "dev"


_current_identity: contextvars.ContextVar[RequestIdentity] = contextvars.ContextVar(
    "research_copilot_identity", default=RequestIdentity()
)


def set_identity(session_id: str, user_id: str = "unknown", prompt_version: str = "unknown", environment: str = "dev") -> contextvars.Token:
    identity = RequestIdentity(session_id=session_id, user_id=user_id, prompt_version=prompt_version, environment=environment)
    return _current_identity.set(identity)


def reset_identity(token: contextvars.Token) -> None:
    _current_identity.reset(token)


# Phase 7, step 44 (plan Q6b): the collector's tail sampler keeps ~20% of
# normal traffic, but one run spans several traces (/research, then
# /approve), and independent per-trace sampling would keep both halves of a
# run only ~4% of the time. So the keep/drop decision is made per SESSION,
# here, deterministically from session_id, and stamped on every span; the
# collector's session-sampled policy only reads it. Traces with no
# session_id (e.g. /health) never carry the flag, so they are kept only if
# they error or contain an expensive model call.
SESSION_SAMPLED_ATTRIBUTE = "trace.session_sampled"


def session_sampled(session_id: str) -> bool:
    """Same answer for the same session_id in every process, so all traces
    of one run are kept or dropped together. TRACE_SESSION_SAMPLE_RATE is
    read per call, not at import, so .env load order can't change it;
    the Step 47 load test sets it to 1.0 to keep everything (plan Q9)."""
    rate = float(os.getenv("TRACE_SESSION_SAMPLE_RATE", "0.2"))
    bucket = int.from_bytes(hashlib.sha256(session_id.encode()).digest()[:8], "big") / 2**64
    return bucket < rate


class IdentitySpanProcessor(SpanProcessor):
    def on_start(self, span, parent_context=None):
        identity = _current_identity.get()
        if identity.session_id:
            span.set_attribute("session_id", identity.session_id)
            span.set_attribute(SESSION_SAMPLED_ATTRIBUTE, session_sampled(identity.session_id))
        if identity.user_id:
            span.set_attribute("user_id", identity.user_id)
        span.set_attribute("prompt_version", identity.prompt_version)
        span.set_attribute("environment", identity.environment)

    def on_end(self, span):
        pass

    def shutdown(self):
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True
