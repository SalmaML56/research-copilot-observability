"""
Phase 3, steps 20-21: run the agent with OpenInference OTel auto-
instrumentation active — sends spans straight to our Collector, no
Langfuse callback involved in this run.

Run:
    docker compose up -d
    uv run python -m research_copilot.agents.run_otel_demo
    docker compose logs otel-collector | tail -60
"""

import uuid

from research_copilot.observability.otel_setup import setup_otel_instrumentation

# Must instrument BEFORE importing/building the agent.
setup_otel_instrumentation()

from research_copilot.agents.main_agent import agent  # noqa: E402
from research_copilot.observability.identity import set_identity, reset_identity  # noqa: E402


if __name__ == "__main__":
    session_id = f"step32-grafana-search-{uuid.uuid4().hex[:6]}"
    task = "Research the CAP theorem in distributed systems and write a short summary."
    print(f"Task: {task}")
    print(f"Session ID (for Grafana search): {session_id}\n")

    identity_token = set_identity(session_id=session_id, user_id="step32-user", environment="dev")
    try:
        result = agent.invoke({"messages": [{"role": "user", "content": task}]})
    finally:
        reset_identity(identity_token)

    print("=== Answer ===")
    print(result["messages"][-1].content)
    print("\nCheck `docker compose logs otel-collector` for OpenInference spans.")
