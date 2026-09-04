"""
Phase 1, step 9: checkpointer (SQLite). Confirmed working.

Phase 1, step 10: human-in-the-loop pause via create_deep_agent's native
interrupt_on parameter. Verified end to end with THREAD_ID
"phase1-step10-demo-thread-v2" (v1 thread was left in a confused state by
an earlier resume-format bug and abandoned rather than debugged further).

Run to trigger the pause:
    uv run python -m research_copilot.agents.checkpointed_agent "Research small modular nuclear reactors and write a short report."
"""

import sys

from langgraph.checkpoint.sqlite import SqliteSaver
from deepagents import create_deep_agent
from langchain.agents.middleware import TodoListMiddleware

from research_copilot.agents.subagents import researcher, writer, LEAD_AGENT_SYSTEM_PROMPT
from research_copilot.agents.tools import finalize_report
from research_copilot.config.settings import settings

settings.validate()

THREAD_ID = "phase1-step10-demo-thread-v2"
CHECKPOINT_DB_PATH = "checkpoints.sqlite"


def build_agent(checkpointer):
    return create_deep_agent(
        model=settings.default_model,
        tools=[finalize_report],
        subagents=[researcher, writer],
        middleware=[TodoListMiddleware()],
        interrupt_on={"finalize_report": True},
        system_prompt=LEAD_AGENT_SYSTEM_PROMPT,
        checkpointer=checkpointer,
    )


def main() -> None:
    if len(sys.argv) < 2:
        print('Usage: uv run python -m research_copilot.agents.checkpointed_agent "your task"')
        sys.exit(1)

    user_message = sys.argv[1]

    with SqliteSaver.from_conn_string(CHECKPOINT_DB_PATH) as checkpointer:
        agent = build_agent(checkpointer)
        config = {"configurable": {"thread_id": THREAD_ID}}

        print(f"Sending: {user_message}\n")
        result = agent.invoke(
            {"messages": [{"role": "user", "content": user_message}]},
            config=config,
        )

        state = agent.get_state(config)
        if state.next:
            print("=== PAUSED — awaiting human approval ===")
            print(f"Next node(s): {state.next}")
        else:
            print("=== Agent's answer (no pending interrupt) ===")
            print(result["messages"][-1].content)


if __name__ == "__main__":
    main()
