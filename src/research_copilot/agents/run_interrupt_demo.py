"""
Phase 1, step 10: approve a pending human-in-the-loop interrupt and resume
the agent. Run this AFTER checkpointed_agent.py has paused on
finalize_report.

Verified against langchain.agents.middleware.human_in_the_loop's actual
source: after_model() reads `interrupt(hitl_request)["decisions"]`, so the
resume payload must be a dict with a "decisions" key containing one
decision per interrupted tool call.

Run:
    uv run python -m research_copilot.agents.run_interrupt_demo
"""

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from research_copilot.agents.checkpointed_agent import (
    build_agent,
    THREAD_ID,
    CHECKPOINT_DB_PATH,
)


def main() -> None:
    with SqliteSaver.from_conn_string(CHECKPOINT_DB_PATH) as checkpointer:
        agent = build_agent(checkpointer)
        config = {"configurable": {"thread_id": THREAD_ID}}

        state = agent.get_state(config)
        if not state.next:
            print("No pending interrupt found on this thread — nothing to approve.")
            return

        print("Found a pending interrupt. Approving 'finalize_report'...\n")

        result = agent.invoke(
            Command(resume={"decisions": [{"type": "approve"}]}),
            config=config,
        )

        print("=== Resumed after approval ===\n")
        final_message = result["messages"][-1]
        print(final_message.content)

        state_after = agent.get_state(config)
        if state_after.next:
            print(f"\nNote: still paused — next node(s): {state_after.next}")
        else:
            print("\nRun completed — no further pending interrupts.")


if __name__ == "__main__":
    main()
