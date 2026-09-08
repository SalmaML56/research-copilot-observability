"""
Phase 1, steps 7 & 8.
Run:
    uv run python -m research_copilot.agents.main_agent
"""

from deepagents import create_deep_agent
from langchain.agents.middleware import TodoListMiddleware

from research_copilot.agents.subagents import researcher, writer, LEAD_AGENT_SYSTEM_PROMPT
from research_copilot.agents.tools import finalize_report
from research_copilot.config.settings import settings
from research_copilot.observability.langfuse_setup import get_langfuse_handler

settings.validate()

agent = create_deep_agent(
    model=settings.default_model,
    tools=[finalize_report],
    subagents=[researcher, writer],
    middleware=[TodoListMiddleware()],
    system_prompt=LEAD_AGENT_SYSTEM_PROMPT,
)


if __name__ == "__main__":
    task = (
        "Research the current state of small modular nuclear reactors "
        "(SMRs) and write a short report covering: (1) what they are, "
        "(2) which companies are furthest along, (3) main challenges. "
        "Save your research notes to 'smr_notes.md', then write the final "
        "report."
    )
    print(f"Task: {task}\n")

    result = agent.invoke(
        {"messages": [{"role": "user", "content": task}]},
        config={
            "callbacks": [get_langfuse_handler()],
            "metadata": {
                "langfuse_session_id": "demo-session-001",
                "langfuse_user_id": "demo-user-salma",
            },
        },
    )

    final_message = result["messages"][-1]
    print("=== Final answer ===\n")
    print(final_message.content)

    print("\n=== Step 8 verification ===")
    todos = result.get("todos")
    print(f"Todo list items written: {len(todos) if todos else 0}")
    if todos:
        for t in todos:
            print(f"  - {t}")

    files = result.get("files")
    print(f"\nFiles in virtual filesystem: {list(files.keys()) if files else 'none'}")
