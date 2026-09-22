"""
Shared LangChain callback for capturing tool activity during an agent run.

Extracted from capture_runs.py (Step 38) so Step 40's inline online-eval
sampling in api/main.py can reuse the exact same collector instead of a
second copy.

Why a callback collector instead of reading result["messages"]: the
researcher subagent calls web_search, so those ToolMessages are not in the
lead agent's message list. Callbacks propagate into subagents.
"""

from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

SEARCH_TOOL = "web_search"


class ToolCollector(BaseCallbackHandler):
    """Records every tool call in order, and the outputs of web_search."""

    def __init__(self) -> None:
        self.tool_calls: list[str] = []
        self.search_outputs: list[str] = []
        self._names: dict[Any, str] = {}

    def on_tool_start(self, serialized, input_str, *, run_id, **kwargs):
        name = kwargs.get("name") or (serialized or {}).get("name") or "unknown"
        self._names[run_id] = name
        self.tool_calls.append(name)

    def on_tool_end(self, output, *, run_id, **kwargs):
        if self._names.get(run_id) == SEARCH_TOOL:
            self.search_outputs.append(getattr(output, "content", output) if output is not None else "")
