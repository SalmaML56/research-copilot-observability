"""
Phase 1, step 6: hello-world Deep Agent with ONE tool (web_search).

This is deliberately the simplest possible agent — no subagents yet (that's
step 7), no checkpointer (step 9), no streaming (step 11). The only goal
here is to prove the wiring works: model + one tool + a real question,
end to end.

Run:
    uv run python -m research_copilot.agents.hello_world
"""

from deepagents import create_deep_agent

from research_copilot.agents.tools import web_search
from research_copilot.config.settings import settings

settings.validate()  # fail fast if ANTHROPIC_API_KEY is missing

agent = create_deep_agent(
    model=settings.default_model,
    tools=[web_search],
    system_prompt=(
        "You are a research assistant. When asked a question that needs "
        "current information, use the web_search tool before answering. "
        "Cite what you found briefly."
    ),
)

if __name__ == "__main__":
    question = "What is the current version of Python, as of today?"
    print(f"Asking: {question}\n")

    # .invoke() runs the agent to completion and returns the final state.
    # We only care about the last message here — later (step 11) we'll
    # switch to .stream() to see intermediate steps as they happen.
    result = agent.invoke({"messages": [{"role": "user", "content": question}]})

    final_message = result["messages"][-1]
    print("Agent's answer:\n")
    print(final_message.content)
