"""
Phase 4, step 30: FastAPI wrapper around the agent.

POST /research — runs the agent on a given topic.
POST /research/{thread_id}/approve — approves a paused finalize_report
call, so the API is actually usable end to end.

Run:
    docker compose up -d
    uv run uvicorn research_copilot.api.main:app --reload
"""

import uuid

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from research_copilot.agents.checkpointed_agent import build_agent, CHECKPOINT_DB_PATH
from research_copilot.observability.otel_setup import setup_otel_instrumentation

provider = setup_otel_instrumentation()

app = FastAPI(title="Research Copilot API")
FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)


class ResearchRequest(BaseModel):
    topic: str
    thread_id: str | None = None


class ResearchResponse(BaseModel):
    thread_id: str
    status: str
    answer: str | None = None


@app.post("/research", response_model=ResearchResponse)
def research(request: ResearchRequest) -> ResearchResponse:
    thread_id = request.thread_id or str(uuid.uuid4())

    with SqliteSaver.from_conn_string(CHECKPOINT_DB_PATH) as checkpointer:
        agent = build_agent(checkpointer)
        config = {"configurable": {"thread_id": thread_id}}

        result = agent.invoke(
            {"messages": [{"role": "user", "content": request.topic}]},
            config=config,
        )

        state = agent.get_state(config)
        if state.next:
            return ResearchResponse(thread_id=thread_id, status="paused_for_approval")

        return ResearchResponse(
            thread_id=thread_id,
            status="completed",
            answer=result["messages"][-1].content,
        )


@app.post("/research/{thread_id}/approve", response_model=ResearchResponse)
def approve(thread_id: str) -> ResearchResponse:
    """
    Approves a paused finalize_report call and lets the run complete.
    Resume shape verified from langchain's HumanInTheLoopMiddleware source:
    Command(resume={"decisions": [{"type": "approve"}]}).
    """
    with SqliteSaver.from_conn_string(CHECKPOINT_DB_PATH) as checkpointer:
        agent = build_agent(checkpointer)
        config = {"configurable": {"thread_id": thread_id}}

        state = agent.get_state(config)
        if not state.next:
            raise HTTPException(
                status_code=400,
                detail="No pending approval found on this thread_id.",
            )

        result = agent.invoke(
            Command(resume={"decisions": [{"type": "approve"}]}),
            config=config,
        )

        return ResearchResponse(
            thread_id=thread_id,
            status="completed",
            answer=result["messages"][-1].content,
        )


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
