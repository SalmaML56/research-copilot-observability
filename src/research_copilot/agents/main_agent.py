"""
Phase 1, steps 7 & 8.

Step 7: add two subagents — researcher (search + file-write tools) and
writer (file-read tool only, no search). The main agent delegates to both
via the built-in `task` tool.

Step 8: confirm the built-in planner/filesystem works — the agent should
write itself a todo list and save research notes to its virtual filesystem
(NOT real disk — this is an in-memory files dict on the agent's state, see
DeepAgentState) on a multistep task.

NOTE: prompts trimmed vs. the original draft to stay under Groq's
free-tier token-per-minute limit (8,000 TPM on openai/gpt-oss-120b).

Run:
    uv run python -m research_copilot.agents.main_agent
"""

from deepagents import create_deep_agent, FilesystemMiddleware
from langchain.agents.middleware import TodoListMiddleware

from research_copilot.agents.tools import web_search
from research_copilot.config.settings import settings

settings.validate()

# --- Researcher subagent -----------------------------------------------
researcher = {
    "name": "researcher",
    "description": (
        "Searches the web on a subtopic and writes findings to a notes "
        "file. Give it a narrow question and a filename to save to."
    ),
    "tools": [web_search],
    "middleware": [FilesystemMiddleware(tools=["read_file", "write_file", "ls"])],
    "system_prompt": (
        "Research subagent. Use web_search on the given topic, then write "
        "a concise factual summary with sources to the given notes file. "
        "No final report — notes only."
    ),
}

# --- Writer subagent ------------------------------------------------------
writer = {
    "name": "writer",
    "description": (
        "Reads researcher's notes and writes the final report. Use only "
        "after notes already exist."
    ),
    "tools": [],
    "middleware": [FilesystemMiddleware(tools=["read_file", "ls"])],
    "system_prompt": (
        "Writer subagent. No web access, no write access. Read the given "
        "notes file(s), then write a clear report from that content only."
    ),
}

agent = create_deep_agent(
    model=settings.default_model,
    subagents=[researcher, writer],
    middleware=[TodoListMiddleware()],
    system_prompt=(
        "Lead agent. Plan the task briefly, delegate web research to "
        "'researcher' (give it the search topic and a filename), then once "
        "notes exist, delegate writing to 'writer' (give it the filename). "
        "Don't search or write files yourself. If a subagent reports it completed its task, TRUST that its file writes succeeded — do not redo its work or claim the file handoff failed unless you explicitly try read_file and get a real error."
    ),
)


if __name__ == "__main__":
    # Shorter task — same intent, fewer tokens
    task = (
        "Research small modular nuclear reactors (SMRs): what they are, "
        "leading companies, main challenges. Save notes to 'smr_notes.md', "
        "then write the final report."
    )
    print(f"Task: {task}\n")

    result = agent.invoke({"messages": [{"role": "user", "content": task}]})

    final_message = result["messages"][-1]
    print("=== Final answer ===\n")
    print(final_message.content)

    # Step 8 verification: confirm the agent actually used the planner and
    # the virtual filesystem, not just answered directly from the model.
    print("\n=== Step 8 verification ===")

    todos = result.get("todos")
    print(f"Todo list items written: {len(todos) if todos else 0}")
    if todos:
        for t in todos:
            print(f"  - {t}")

    files = result.get("files")
    print(f"\nFiles in virtual filesystem: {list(files.keys()) if files else 'none'}")
    if files and "smr_notes.md" in files:
        print("\n'smr_notes.md' was created by the researcher subagent — confirmed.")
