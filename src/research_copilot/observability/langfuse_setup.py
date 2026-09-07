"""
Phase 2, step 15: Langfuse tracing setup.

The `langfuse` package (v4.x) automatically reads LANGFUSE_PUBLIC_KEY,
LANGFUSE_SECRET_KEY, and LANGFUSE_HOST from the environment — we don't
pass keys directly to the CallbackHandler.

Usage: pass config={"callbacks": [get_langfuse_handler()]} to any
agent.invoke() / agent.stream() call.
"""

from langfuse.langchain import CallbackHandler


def get_langfuse_handler() -> CallbackHandler:
    """Returns a fresh Langfuse callback handler for one agent run."""
    return CallbackHandler()
