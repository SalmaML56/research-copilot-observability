"""
Phase 7, step 47 (plan Q8c): a scripted stand-in for the LLM, selected with
MODEL_PROFILE=stub. The 20-session load test needs 20 concurrent runs that
go through the REAL graph - lead agent, researcher and writer subagents,
virtual filesystem, finalize_report approval pause, Postgres checkpoints,
FastAPI, identity ContextVar, OTel - without 20 concurrent DeepSeek runs.
Only the model call itself is replaced.

It follows the lead-agent workflow deterministically and echoes the run's
marker (the first "LT-..." token in its input) into everything it writes.
So if one session's state, file or messages ever end up in another's
checkpoint or trace, the foreign marker shows it.

Not for real use: no web search happens (the researcher writes notes
without calling web_search, which would hit the network 20x at once).
"""

import random
import re
import time
import uuid
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

_MARKER = re.compile(r"LT-[0-9]+-[0-9a-f]+")


def _text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return " ".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)


def _tool_call(name: str, args: dict) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call_{uuid.uuid4().hex[:12]}"}])


class StubChatModel(BaseChatModel):
    # Random per-call latency, so 20 concurrent runs interleave their model
    # calls, checkpoint writes and spans instead of running in lockstep.
    min_delay: float = 0.2
    max_delay: float = 1.5

    @property
    def _llm_type(self) -> str:
        return "stub"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "StubChatModel":
        return self

    def _generate(self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        time.sleep(random.uniform(self.min_delay, self.max_delay))
        message = self._next(messages)
        message.usage_metadata = {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}
        message.response_metadata = {"model_name": "stub"}
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _next(self, messages: list[BaseMessage]) -> AIMessage:
        system = " ".join(_text(m) for m in messages if isinstance(m, SystemMessage))
        conversation = [m for m in messages if not isinstance(m, SystemMessage)]
        marker_match = _MARKER.search(" ".join(_text(m) for m in conversation[:1]))
        marker = marker_match.group(0) if marker_match else "LT-none"
        done = [m.name for m in conversation if isinstance(m, ToolMessage)]
        notes = f"/notes_{marker}.md"

        if "research subagent" in system:
            if "write_file" not in done:
                return _tool_call("write_file", {"file_path": notes, "content": f"Stub notes for {marker}."})
            return AIMessage(content=f"Notes for {marker} saved to {notes}.")

        if "writer subagent" in system:
            if "read_file" not in done:
                return _tool_call("read_file", {"file_path": notes})
            notes_text = _text([m for m in conversation if isinstance(m, ToolMessage)][-1])
            return AIMessage(content=f"Report for {marker}: {notes_text[-200:]}")

        # Lead agent.
        if done.count("task") == 0:
            return _tool_call("task", {"subagent_type": "researcher",
                                       "description": f"Research {marker}. Save notes to {notes}."})
        if done.count("task") == 1:
            return _tool_call("task", {"subagent_type": "writer",
                                       "description": f"Write the report for {marker} from {notes}."})
        if "finalize_report" not in done:
            report = _text([m for m in conversation if isinstance(m, ToolMessage) and m.name == "task"][-1])
            return _tool_call("finalize_report", {"report_text": report})
        return AIMessage(content=f"Final answer for {marker}.")
