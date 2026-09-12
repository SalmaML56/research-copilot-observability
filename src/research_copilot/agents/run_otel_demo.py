"""
Phase 3, steps 20-21: run the agent with OpenInference OTel auto-
instrumentation active — sends spans straight to our Collector, no
Langfuse callback involved in this run.

Run:
    docker compose up -d
    uv run python -m research_copilot.agents.run_otel_demo
    docker compose logs otel-collector | tail -60
"""

from research_copilot.observability.otel_setup import setup_otel_instrumentation

# Must instrument BEFORE importing/building the agent.
setup_otel_instrumentation()

from research_copilot.agents.main_agent import agent  # noqa: E402


if __name__ == "__main__":
    task = "What is a small modular nuclear reactor? Answer in 2 short sentences, no research needed."
    print(f"Task: {task}\n")

    result = agent.invoke({"messages": [{"role": "user", "content": task}]})

    print("=== Answer ===")
    print(result["messages"][-1].content)
    print("\nCheck `docker compose logs otel-collector` for OpenInference spans.")
