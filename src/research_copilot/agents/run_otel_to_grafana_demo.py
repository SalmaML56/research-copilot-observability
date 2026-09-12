"""
Phase 4, steps 31-32.

Run:
    docker compose up -d otel-collector grafana-lgtm
    uv run python -m research_copilot.agents.run_otel_to_grafana_demo
"""

import uuid

from opentelemetry import trace
from openinference.instrumentation.langchain import LangChainInstrumentor

from research_copilot.observability.otel_setup import setup_otel_instrumentation

provider = setup_otel_instrumentation()
LangChainInstrumentor().instrument(tracer_provider=provider)

from research_copilot.agents.main_agent import agent  # noqa: E402

tracer = trace.get_tracer("research_copilot.grafana_demo")

SESSION_ID = "grafana-demo-session-001"


if __name__ == "__main__":
    task = "Search the web briefly for what year the Eiffel Tower was built, and answer in one sentence."
    print(f"Task: {task}")
    print(f"Session ID (search for this in Grafana/Tempo): {SESSION_ID}\n")

    with tracer.start_as_current_span("agent.request") as span:
        span.set_attribute("session_id", SESSION_ID)
        span.set_attribute("gen_ai.conversation.id", SESSION_ID)
        span.set_attribute("request.id", str(uuid.uuid4()))

        result = agent.invoke({"messages": [{"role": "user", "content": task}]})

    print("=== Answer ===")
    print(result["messages"][-1].content)

    provider.force_flush()
    print(f"\nDone. In Grafana (http://localhost:3001) -> Explore -> Tempo, search TraceQL:")
    print(f'  {{ span.session_id = "{SESSION_ID}" }}')
