"""
Phase 1, step 9: add a checkpointer (SQLite first, Postgres later).

Run TWICE, as two separate `uv run` calls, with the SAME thread_id, to
prove real cross-process resume:

    uv run python -m research_copilot.agents.checkpointed_agent "What is a small modular reactor? Answer in 2 short sentences."
    uv run python -m research_copilot.agents.checkpointed_agent "What did I just ask you about?"
"""

import sys

from langgraph.checkpoint.sqlite import SqliteSaver

from deepagents import create_deep_agent
from langchain.agents.middleware import TodoListMiddleware

from research_copilot.agents.subagents import researcher, writer, LEAD_AGENT_SYSTEM_PROMPT
from research_copilot.config.settings import settings

settings.validate()

THREAD_ID = "phase1-step9-demo-thread"
CHECKPOINT_DB_PATH = "checkpoints.sqlite"


def main() -> None:
    if len(sys.argv) < 2:
        print('Usage: uv run python -m research_copilot.agents.checkpointed_agent "your message"')
        sys.exit(1)

    user_message = sys.argv[1]

    with SqliteSaver.from_conn_string(CHECKPOINT_DB_PATH) as checkpointer:
        agent = create_deep_agent(
            model=settings.default_model,
            subagents=[researcher, writer],
            middleware=[TodoListMiddleware()],
            system_prompt=LEAD_AGENT_SYSTEM_PROMPT,
            checkpointer=checkpointer,
        )

        config = {"configurable": {"thread_id": THREAD_ID}}

        existing_state = agent.get_state(config)
        had_prior_state = bool(existing_state.values.get("messages"))

        print(f"Thread '{THREAD_ID}' had prior saved state: {had_prior_state}")
        if had_prior_state:
            prior_message_count = len(existing_state.values["messages"])
            print(f"Resuming — {prior_message_count} messages already in checkpoint.\n")
        else:
            print("Starting a brand new conversation on this thread.\n")

        print(f"Sending: {user_message}\n")
        result = agent.invoke(
            {"messages": [{"role": "user", "content": user_message}]},
            config=config,
        )

        print("=== Agent's answer ===")
        print(result["messages"][-1].content)

        print(f"\nTotal messages now saved in checkpoint for this thread: {len(result['messages'])}")


if __name__ == "__main__":
    main()
