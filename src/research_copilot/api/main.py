"""
Phase 4, step 30: FastAPI wrapper around the agent.

POST /research — runs the agent on a given topic.
POST /research/{thread_id}/approve — approves a paused finalize_report
call, so the API is actually usable end to end.
POST /research/stream — Phase 7, step 46: same run as /research, streamed
as Server-Sent Events; ends with a "status" event shaped like
ResearchResponse. A pause is approved through the normal /approve.
POST /research/{thread_id}/feedback — Phase 6, step 43: thumbs up/down on
a completed response, pushed as a "user_feedback" score onto that
response's trace.

Run:
    docker compose up -d
    uv run uvicorn research_copilot.api.main:app --reload
"""

import contextvars
import json
import os
import queue
import random
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from langfuse import get_client
from opentelemetry import trace
from pydantic import BaseModel
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from research_copilot.agents.checkpointed_agent import build_agent, create_checkpoint_pool
from research_copilot.observability.otel_setup import setup_otel_instrumentation
from research_copilot.observability.identity import (
    SESSION_SAMPLED_ATTRIBUTE,
    reset_identity,
    session_sampled,
    set_identity,
)
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

# Phase 7, step 46: checkpoints in Postgres through one process-wide pool.
# The SQLite version opened a fresh connection on every request; with
# PostgresSaver.from_conn_string() that would be a new TCP connection + auth
# per request, against a server whose connection limit is finite. Each
# PostgresSaver only borrows a connection per checkpoint read/write, so
# the pool can be smaller than the number of concurrent runs.
CHECKPOINT_POOL_MAX_SIZE = int(os.getenv("CHECKPOINT_POOL_MAX_SIZE", "10"))
_checkpoint_pool = create_checkpoint_pool(CHECKPOINT_POOL_MAX_SIZE)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _checkpoint_pool.open(wait=True)
    PostgresSaver(_checkpoint_pool).setup()
    try:
        yield
    finally:
        _checkpoint_pool.close()


app = FastAPI(title="Research Copilot API", lifespan=lifespan)
# Phase 7: no per-message ASGI "http send"/"http receive" sub-spans. Each
# SSE chunk from /research/stream got its own span - 1085 of 1270 spans in
# one streamed run's trace - and they carried no identity attributes either.
# The request's root span still records method, route, status and duration.
FastAPIInstrumentor.instrument_app(app, tracer_provider=provider, exclude_spans=["send", "receive"])

# Step 40: online evals. Langfuse's trace-read API isn't usable in this
# deployment (self-hosted, v4 "events_only" mode - trace.list/get 404, and
# observations.get_many never returns input/output content regardless of
# requested fields - verified directly against the running instance). So,
# unlike a normal online-eval setup that would pull sampled trace content
# back out of the observability backend after the fact, this samples and
# captures inline at request time instead, the same way Step 38 does for
# offline runs. Kept out of the 90% non-sampled path entirely: no collector
# object, no extra callback, no file I/O unless sampled.
ONLINE_EVAL_SAMPLE_RATE = float(os.getenv("ONLINE_EVAL_SAMPLE_RATE", "0.1"))
ONLINE_SAMPLES_PATH = Path("data/eval_results/online_samples.jsonl")
# LEAD_AGENT_SYSTEM_PROMPT requires human approval before finalize_report on
# every run, so research() essentially never returns "completed" directly -
# confirmed live: 2/2 smoke-test requests paused and completed via /approve
# instead. web_search happens in research()'s invoke(), before the pause,
# so the sampled ToolCollector's data has to survive to whichever request
# actually produces "completed" - hence a pending-capture file per
# thread_id instead of capturing inline in research() alone.
ONLINE_PENDING_DIR = Path("data/eval_results/online_pending")

# Step 43: human feedback (thumbs up/down) on a completed response, pushed
# as a score onto that response's own trace. The trace_id a completed
# response was produced under lives only on that request's OTel span, which
# is long closed by the time feedback arrives on a separate HTTP request -
# so it has to be persisted keyed by thread_id, the same id the client
# already holds (it needed it for /approve). Same pattern as
# ONLINE_PENDING_DIR: one small file per thread_id, best-effort I/O.
COMPLETED_TRACE_DIR = Path("data/eval_results/completed_traces")


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
    trace_id: str | None = None


class FeedbackRequest(BaseModel):
    thumbs_up: bool


class FeedbackResponse(BaseModel):
    thread_id: str
    trace_id: str
    recorded: bool


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
        root_span.set_attribute(SESSION_SAMPLED_ATTRIBUTE, session_sampled(thread_id))
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


def _current_trace_id() -> str:
    return format(trace.get_current_span().get_span_context().trace_id, "032x")


def _record_online_sample(
    thread_id: str, topic: str, user_id: str, answer: str, retrieval_context: list, tool_calls: list
) -> None:
    """Best-effort only: must never fail or slow down the request it rode in
    on. A trace/answer worth scoring was already produced either way."""
    try:
        trace_id = _current_trace_id()
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


def _record_completed_trace(thread_id: str, trace_id: str) -> None:
    """Best-effort only, same rule as _record_online_sample: must never fail
    or slow down the request that produced a real, completed answer."""
    try:
        COMPLETED_TRACE_DIR.mkdir(parents=True, exist_ok=True)
        (COMPLETED_TRACE_DIR / f"{thread_id}.json").write_text(json.dumps({"trace_id": trace_id}))
    except Exception:
        log.warning("completed trace record failed", exc_info=True)


def _get_completed_trace(thread_id: str) -> str | None:
    path = COMPLETED_TRACE_DIR / f"{thread_id}.json"
    try:
        if not path.exists():
            return None
        return json.loads(path.read_text())["trace_id"]
    except Exception:
        log.warning("completed trace read failed", exc_info=True)
        return None


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
        # A new saver per request over the shared pool, never one shared
        # saver: each PostgresSaver serializes all its DB operations behind
        # its own lock (see create_checkpoint_pool).
        agent = build_agent(PostgresSaver(_checkpoint_pool))
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
        trace_id = _current_trace_id()
        _record_completed_trace(thread_id, trace_id)
        if collector is not None:
            _record_online_sample(
                thread_id, request.topic, request.user_id, answer, collector.search_outputs, collector.tool_calls
            )
        return ResearchResponse(
            thread_id=thread_id,
            status="completed",
            answer=answer,
            trace_id=trace_id,
        )
    finally:
        reset_identity(identity_token)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _stream_source(namespace: tuple) -> str:
    """Lead agent, or the subagent path the event came from."""
    if not namespace:
        return "lead-agent"
    return " > ".join(part.split(":")[0] for part in namespace)


@app.post("/research/stream")
def research_stream(request: ResearchRequest) -> StreamingResponse:
    """
    Phase 7, step 46: streaming variant of /research, as Server-Sent Events:
    "token" (model text chunks), "tool_call" (tool names only - args can be
    whole reports), then one final "status" event with the same fields as
    ResearchResponse.

    The agent runs on ONE worker thread started under a copy of this
    handler's context, feeding a queue the response generator drains.
    Iterating agent.stream() directly inside the generator does not work:
    Starlette runs each next() of a sync generator in a separate
    anyio.to_thread.run_sync call, each with a fresh copy of the request
    context (verified in starlette 1.6.0's iterate_in_threadpool), so the
    identity ContextVar and the OTel parent span set up here would not be
    reliably visible to the agent's spans, and spans could start and end in
    different contexts.

    Not included here, unlike /research: Step 40 online-eval sampling. If
    the client disconnects, the run still finishes and is checkpointed; it
    can be approved as usual.
    """
    thread_id = request.thread_id or str(uuid.uuid4())
    identity_token = _begin_request(thread_id, request.user_id)
    try:
        log.info("research stream request received", extra={"topic": request.topic})
        run_context = contextvars.copy_context()
    finally:
        reset_identity(identity_token)

    events: queue.Queue[str | None] = queue.Queue()

    def run_agent() -> None:
        try:
            agent = build_agent(PostgresSaver(_checkpoint_pool))
            config = {
                "configurable": {"thread_id": thread_id},
                "callbacks": [GenAIMetricsCallbackHandler()],
            }
            for namespace, mode, chunk in agent.stream(
                {"messages": [{"role": "user", "content": request.topic}]},
                config=config,
                stream_mode=["updates", "messages"],
                subgraphs=True,
            ):
                source = _stream_source(namespace)
                if mode == "messages":
                    text = _extract_text_content(getattr(chunk[0], "content", ""))
                    if text:
                        events.put(_sse("token", {"source": source, "text": text}))
                elif mode == "updates":
                    for node_output in chunk.values():
                        if not isinstance(node_output, dict):
                            continue
                        for message in node_output.get("messages") or []:
                            for tool_call in getattr(message, "tool_calls", None) or []:
                                events.put(_sse("tool_call", {"source": source, "name": tool_call.get("name")}))

            state = agent.get_state(config)
            record_run_steps(len(state.values.get("todos") or []))
            if state.next:
                mark_pending_approval(thread_id)
                log.info("research paused for approval")
                response = ResearchResponse(thread_id=thread_id, status="paused_for_approval")
            else:
                clear_pending_approval(thread_id)
                log.info("research completed")
                trace_id = _current_trace_id()
                _record_completed_trace(thread_id, trace_id)
                response = ResearchResponse(
                    thread_id=thread_id,
                    status="completed",
                    answer=_extract_text_content(state.values["messages"][-1].content),
                    trace_id=trace_id,
                )
            events.put(_sse("status", response.model_dump()))
        except Exception as exc:
            log.exception("research stream failed")
            events.put(_sse("error", {"thread_id": thread_id, "error": repr(exc)}))
        finally:
            events.put(None)

    threading.Thread(target=run_context.run, args=(run_agent,), daemon=True).start()

    def drain():
        while (item := events.get()) is not None:
            yield item

    return StreamingResponse(drain(), media_type="text/event-stream")


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
        # Per-request saver, same reason as in research().
        agent = build_agent(PostgresSaver(_checkpoint_pool))
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
        trace_id = _current_trace_id()
        _record_completed_trace(thread_id, trace_id)
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
            trace_id=trace_id,
        )
    finally:
        reset_identity(identity_token)


@app.post("/research/{thread_id}/feedback", response_model=FeedbackResponse)
def feedback(thread_id: str, request: FeedbackRequest) -> FeedbackResponse:
    """
    Thumbs up/down on a completed response, pushed as a score onto that
    response's own trace (looked up via _get_completed_trace - see
    COMPLETED_TRACE_DIR's docstring for why this can't just read the
    current span's trace_id, unlike _record_online_sample).

    Explicit flush(): unlike the rest of this long-running app (which
    relies on Langfuse's background batching), user feedback is low-volume
    and each one is worth losing a request-latency margin for - this repo
    has already lost in-flight background work to unrelated process
    restarts more than once this session, and a queued-but-unflushed score
    would silently vanish the same way.
    """
    trace_id = _get_completed_trace(thread_id)
    if trace_id is None:
        raise HTTPException(
            status_code=404,
            detail="No completed response found for this thread_id.",
        )
    get_client().create_score(
        trace_id=trace_id,
        name="user_feedback",
        value=1.0 if request.thumbs_up else 0.0,
        data_type="BOOLEAN",
    )
    get_client().flush()
    log.info("feedback recorded", extra={"thread_id": thread_id, "thumbs_up": request.thumbs_up})
    return FeedbackResponse(thread_id=thread_id, trace_id=trace_id, recorded=True)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
