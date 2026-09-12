"""
Phase 2, step 19: LangGraph Studio entrypoint.

The `langgraph dev` server manages its own checkpointing/persistence layer
automatically — unlike checkpointed_agent.py, this file exports a COMPILED
graph with NO externally-supplied checkpointer, per LangChain's own
official template project structure.

Referenced from langgraph.json as: research_copilot.agents.studio_agent:graph

Run:
    uv run langgraph dev --tunnel
"""

from deepagents import create_deep_agent
from langchain.agents.middleware import TodoListMiddleware

from research_copilot.agents.subagents import researcher, writer, LEAD_AGENT_SYSTEM_PROMPT
from research_copilot.agents.tools import finalize_report
from research_copilot.config.settings import settings

settings.validate()

graph = create_deep_agent(
    model=settings.default_model,
    tools=[finalize_report],
    subagents=[researcher, writer],
    middleware=[TodoListMiddleware()],
    interrupt_on={"finalize_report": True},
    system_prompt=LEAD_AGENT_SYSTEM_PROMPT,
)
