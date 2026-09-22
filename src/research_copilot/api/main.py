"""
Phase 4, step 30: FastAPI wrapper around the agent.

POST /research — runs the agent on a given topic.
POST /research/{thread_id}/approve — approves a paused finalize_report
call, so the API is actually usable end to end.

Run:
    docker compose up -d
    uv run uvicorn research_copilot.api.main:app --reload
"""

import json
import random
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from opentelemetry import trace
from pydantic import BaseModel
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from research_copilot.agents.checkpointed_agent import build_agent, CHECKPOINT_DB_PATH
from research_copilot.observability.otel_setup import setup_otel_instrumentation
from research_copilot.observability.identity import set_identity, reset_identity
from research_copilot.observability.metrics_setup import (
    setup_metrics_instrumentation,
    GenAIMetricsCallbackHandler,
    record_run_steps,
    mark_pending_approval,
    clear_pending_approval,
)
from research_copilot.observability.logging_setup import setup_logging
from research_copilot.config.settings import settings
from research_copilot.evals.tool_collector import ToolCollector

provider = setup_otel_instrumentation()
setup_metrics_instrumentation()
log = setup_logging()

app = FastAPI(title="Research Copilot API")
FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)

# Step 40: online evals. Langfuse's trace-read API isn't usable in this
# deployment (self-hosted, v4 "events_only" mode - trace.list/get 404, and
# observations.get_many never returns input/output content regardless of
# requested fields - verified directly against the running instance). So,
# unlike a normal online-eval setup that would pull sampled trace content
# back out of the observability backend after the fact, this samples and
# captures inline at request time instead, the same way Step 38 does for
# offline runs. Kept out of the 90% non-sampled path entirely: no collector
# object, no extra callback, no file I/O unless sampled.
ONLINE_EVAL_SAMPLE_RATE = 0.1
ONLINE_SAMPLES_PATH = Path("data/eval_results/online_samples.jsonl")
# LEAD_AGENT_SYSTEM_PROMPT requires human approval before finalize_report on
# every run, so research() essentially never returns "completed" directly -
# confirmed live: 2/2 smoke-test requests paused and completed via /approve
# instead. web_search happens in research()'s invoke(), before the pause,
# so the sampled ToolCollector's data has to survive to whichever request
# actually produces "completed" - hence a pending-capture file per
# thread_id instead of capturing inline in research() alone.
ONLINE_PENDING_DIR = Path("data/eval_results/online_pending")


class ResearchRequest(BaseModel):
    topic: str
    thread_id: str | None = None
    # Phase 5, P5-41 (Step 36b): the per-user cost-spike alert cannot
    # distinguish users while every request is identified as "unknown".
    # Accepting a real user_id here is what makes that alert meaningful.
    user_id: str = "unknown"


class ResearchResponse(BaseModel):
    thread_id: str
    status: str
    answer: str | None = None


def _begin_request(thread_id: str, user_id: str):
    """Sets request identity and stamps it on the FastAPI root span.

    Review v2 (Steps 5/24/30) flagged that the HTTP root span and its ASGI
    sub-spans carried none of the identity attributes, because
    FastAPIInstrumentor starts that span before the route handler body runs
    and IdentitySpanProcessor.on_start only fires for spans started after
    set_identity(). The root span is the *current* span here, so stamping it
    directly closes that gap - the span is still open, attributes set now
    are exported with it.
    """
    token = set_identity(
        session_id=thread_id,
        user_id=user_id,
        prompt_version=settings.prompt_version,
        environment=settings.environment,
    )
    root_span = trace.get_current_span()
    if root_span.get_span_context().is_valid:
        root_span.set_attribute("session_id", thread_id)
        root_span.set_attribute("user_id", user_id)
        root_span.set_attribute("prompt_version", settings.prompt_version)
        root_span.set_attribute("environment", settings.environment)
    return token


def _count_planned_steps(result) -> int:
    """Step 35 "average steps per run" / Step 36a "run exceeded 25 steps".

    TodoListMiddleware keeps the plan under the "todos" state key.
    """
    todos = result.get("todos") if isinstance(result, dict) else None
    return len(todos or [])


def _extract_text_content(content) -> str:
    """
    Step 30 fix: message.content is normally a plain string, but some
    model/agent paths return a list of content blocks
    (e.g. [{"type": "text", "text": "..."}]). Returning that list
    directly as ResearchResponse.answer (str | None) fails Pydantic
    validation and crashes the endpoint with a 500. Normalize both shapes
    to a plain string here.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return str(content)


def _record_online_sample(
    thread_id: str, topic: str, user_id: str, answer: str, retrieval_context: list, tool_calls: list
) -> None:
    """Best-effort only: must never fail or slow down the request it rode in
    on. A trace/answer worth scoring was already produced either way."""
    try:
        trace_id = format(trace.get_current_span().get_span_context().trace_id, "032x")
        row = {
            "id": thread_id,
            "prompt": topic,
            "user_id": user_id,
            "answer": answer,
            "retrieval_context": retrieval_context,
            "tool_calls": tool_calls,
            "trace_id": trace_id,
        }
        ONLINE_SAMPLES_PATH.parent.mkdir(parents=True, exist_ok=True)
        with ONLINE_SAMPLES_PATH.open("a") as f:
            f.write(json.dumps(row) + "\n")
    except Exception:
        log.warning("online eval sample capture failed", exc_info=True)


def _write_pending_capture(thread_id: str, topic: str, user_id: str, collector: ToolCollector) -> None:
    """Written when a sampled run pauses for approval, since the search
    activity already happened but there's no answer yet."""
    try:
        ONLINE_PENDING_DIR.mkdir(parents=True, exist_ok=True)
        row = {
            "prompt": topic,
            "user_id": user_id,
            "retrieval_context": collector.search_outputs,
            "tool_calls": collector.tool_calls,
        }
        (ONLINE_PENDING_DIR / f"{thread_id}.json").write_text(json.dumps(row))
    except Exception:
        log.warning("online eval pending capture failed", exc_info=True)


def _pop_pending_capture(thread_id: str) -> dict | None:
    """Returns and deletes the pending capture for thread_id, if any. Absence
    is the normal case (not sampled, or no approval pause happened) - not an
    error."""
    path = ONLINE_PENDING_DIR / f"{thread_id}.json"
    try:
        if not path.exists():
            return None
        row = json.loads(path.read_text())
        path.unlink()
        return row
    except Exception:
        log.warning("online eval pending capture read failed", exc_info=True)
        return None


@app.post("/research", response_model=ResearchResponse)
def research(request: ResearchRequest) -> ResearchResponse:
    thread_id = request.thread_id or str(uuid.uuid4())
    identity_token = _begin_request(thread_id, request.user_id)
    log.info("research request received", extra={"topic": request.topic})
    # Sampled once per request, before any tracing/collector cost is paid -
    # the other ~90% take none of this path.
    sampled = random.random() < ONLINE_EVAL_SAMPLE_RATE
    collector = ToolCollector() if sampled else None
    try:
        with SqliteSaver.from_conn_string(CHECKPOINT_DB_PATH) as checkpointer:
            agent = build_agent(checkpointer)
            config = {"configurable": {"thread_id": thread_id}}

            config["callbacks"] = [GenAIMetricsCallbackHandler()]
            if collector is not None:
                config["callbacks"].append(collector)
            result = agent.invoke(
                {"messages": [{"role": "user", "content": request.topic}]},
                config=config,
            )

            record_run_steps(_count_planned_steps(result))

            state = agent.get_state(config)
            if state.next:
                mark_pending_approval(thread_id)
                log.info("research paused for approval")
                if collector is not None:
                    _write_pending_capture(thread_id, request.topic, request.user_id, collector)
                return ResearchResponse(thread_id=thread_id, status="paused_for_approval")

            clear_pending_approval(thread_id)
            log.info("research completed")
            answer = _extract_text_content(result["messages"][-1].content)
            if collector is not None:
                _record_online_sample(
                    thread_id, request.topic, request.user_id, answer, collector.search_outputs, collector.tool_calls
                )
            return ResearchResponse(
                thread_id=thread_id,
                status="completed",
                answer=answer,
            )
    finally:
        reset_identity(identity_token)


@app.post("/research/{thread_id}/approve", response_model=ResearchResponse)
def approve(thread_id: str) -> ResearchResponse:
    """
    Approves a paused finalize_report call and lets the run complete.
    Resume shape verified from langchain's HumanInTheLoopMiddleware source:
    Command(resume={"decisions": [{"type": "approve"}]}).
    """
    identity_token = _begin_request(thread_id, "unknown")
    log.info("approval request received")
    try:
        with SqliteSaver.from_conn_string(CHECKPOINT_DB_PATH) as checkpointer:
            agent = build_agent(checkpointer)
            config = {"configurable": {"thread_id": thread_id}}

            state = agent.get_state(config)
            if not state.next:
                clear_pending_approval(thread_id)
                raise HTTPException(
                    status_code=400,
                    detail="No pending approval found on this thread_id.",
                )

            config["callbacks"] = [GenAIMetricsCallbackHandler()]
            result = agent.invoke(
                Command(resume={"decisions": [{"type": "approve"}]}),
                config=config,
            )

            # Step 30 fix: a resume can trigger another pending interrupt
            # (e.g. a second approval-gated tool call). Re-check state
            # instead of unconditionally reporting completed.
            record_run_steps(_count_planned_steps(result))

            new_state = agent.get_state(config)
            if new_state.next:
                mark_pending_approval(thread_id)
                log.info("still paused: another approval is pending")
                return ResearchResponse(thread_id=thread_id, status="paused_for_approval")

            clear_pending_approval(thread_id)
            log.info("run completed after approval")
            answer = _extract_text_content(result["messages"][-1].content)
            pending = _pop_pending_capture(thread_id)
            if pending is not None:
                _record_online_sample(
                    thread_id,
                    pending["prompt"],
                    pending["user_id"],
                    answer,
                    pending["retrieval_context"],
                    pending["tool_calls"],
                )
            return ResearchResponse(
                thread_id=thread_id,
                status="completed",
                answer=answer,
            )
    finally:
        reset_identity(identity_token)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
