"""
Phase 1, step 9: checkpointer (SQLite). Confirmed working.

Phase 7, step 46: checkpoints moved from SQLite to Postgres (the dedicated
checkpoint-postgres service, docs/phase7_plan.md Q3a). The old
checkpoints.sqlite is left on disk untouched; nothing was migrated (Q4a).

Phase 1, step 10: human-in-the-loop pause via create_deep_agent's native
interrupt_on parameter. Verified end to end with THREAD_ID
"phase1-step10-demo-thread-v2" (v1 thread was left in a confused state by
an earlier resume-format bug and abandoned rather than debugged further).

Run to trigger the pause:
    uv run python -m research_copilot.agents.checkpointed_agent "Research small modular nuclear reactors and write a short report."
"""

import sys
from contextlib import contextmanager

from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from deepagents import create_deep_agent
from langchain.agents.middleware import TodoListMiddleware

from research_copilot.agents.subagents import researcher, writer, LEAD_AGENT_SYSTEM_PROMPT
from research_copilot.agents.tools import finalize_report
from research_copilot.config.settings import settings
from research_copilot.observability.metrics_setup import (
    setup_metrics_instrumentation,
    record_run_steps,
    flush_metrics,
)
from research_copilot.observability.logging_setup import setup_logging, flush_logs

settings.validate()

THREAD_ID = "phase1-step10-demo-thread-v2"
CHECKPOINT_DB_URI = settings.checkpoint_db_uri
# PostgresSaver needs these on every connection: autocommit because setup()
# runs CREATE INDEX CONCURRENTLY, dict_row because it reads rows by column
# name. Same values its own from_conn_string() uses - a pool built without
# them breaks the saver.
CHECKPOINT_CONN_KWARGS = {"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row}


@contextmanager
def open_checkpointer():
    """Short-lived processes (this CLI, the Phase 1 demos): one connection
    for the life of the process. setup() is idempotent - it only applies
    migrations the database hasn't seen yet."""
    with PostgresSaver.from_conn_string(CHECKPOINT_DB_URI) as checkpointer:
        checkpointer.setup()
        yield checkpointer


def create_checkpoint_pool(max_size: int) -> ConnectionPool:
    """Long-running processes (the API). Created closed; the caller opens it.

    Callers build a new PostgresSaver(pool) per request rather than sharing
    one: each PostgresSaver holds its own threading.Lock around every DB
    operation (verified in its source), so a single shared saver would
    serialize every concurrent session's checkpoint I/O. The saver only
    borrows a pool connection per operation, so the pool can stay smaller
    than the number of concurrent runs."""
    return ConnectionPool(
        CHECKPOINT_DB_URI,
        min_size=1,
        max_size=max_size,
        kwargs=CHECKPOINT_CONN_KWARGS,
        open=False,
    )


def build_agent(checkpointer):
    return create_deep_agent(
        model=settings.default_model,
        tools=[finalize_report],
        subagents=[researcher, writer],
        middleware=[TodoListMiddleware()],
        interrupt_on={"finalize_report": True},
        system_prompt=LEAD_AGENT_SYSTEM_PROMPT,
        checkpointer=checkpointer,
    )


def main() -> None:
    # Phase 5, P5-26: the CLI path emits metrics and logs too, so a run
    # started from a terminal shows up on the same dashboards as one served
    # over HTTP. Short-lived process, so both are force-flushed at the end -
    # the 5s periodic export would otherwise never fire.
    setup_metrics_instrumentation()
    setup_logging()

    if len(sys.argv) < 2:
        print('Usage: uv run python -m research_copilot.agents.checkpointed_agent "your task"')
        sys.exit(1)

    user_message = sys.argv[1]

    with open_checkpointer() as checkpointer:
        agent = build_agent(checkpointer)
        config = {"configurable": {"thread_id": THREAD_ID}}

        print(f"Sending: {user_message}\n")
        result = agent.invoke(
            {"messages": [{"role": "user", "content": user_message}]},
            config=config,
        )

        record_run_steps(len(result.get("todos") or []))

        state = agent.get_state(config)
        if state.next:
            print("=== PAUSED — awaiting human approval ===")
            print(f"Next node(s): {state.next}")
        else:
            print("=== Agent's answer (no pending interrupt) ===")
            print(result["messages"][-1].content)


if __name__ == "__main__":
    try:
        main()
    finally:
        # Short-lived process: without an explicit flush the 5s periodic
        # metric export and the batched log export never fire, and the run
        # is invisible on every dashboard.
        flush_metrics()
        flush_logs()
