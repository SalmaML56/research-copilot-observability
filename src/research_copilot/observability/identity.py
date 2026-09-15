"""
Fixes the identity-propagation gap (Steps 5, 15, 16, 24, 26, 30): 0 of 71
captured spans had session_id/user_id/prompt_version/environment.
"""

import contextvars
from dataclasses import dataclass

from opentelemetry.sdk.trace import SpanProcessor


@dataclass
class RequestIdentity:
    session_id: str | None = None
    user_id: str | None = None
    prompt_version: str = "v1"
    environment: str = "dev"


_current_identity: contextvars.ContextVar[RequestIdentity] = contextvars.ContextVar(
    "research_copilot_identity", default=RequestIdentity()
)


def set_identity(session_id: str, user_id: str = "unknown", prompt_version: str = "v1", environment: str = "dev") -> contextvars.Token:
    identity = RequestIdentity(session_id=session_id, user_id=user_id, prompt_version=prompt_version, environment=environment)
    return _current_identity.set(identity)


def reset_identity(token: contextvars.Token) -> None:
    _current_identity.reset(token)


class IdentitySpanProcessor(SpanProcessor):
    def on_start(self, span, parent_context=None):
        identity = _current_identity.get()
        if identity.session_id:
            span.set_attribute("session_id", identity.session_id)
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
