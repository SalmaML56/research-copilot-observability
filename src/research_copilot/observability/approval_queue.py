"""
Phase 7, step 48: the human-approval queue, stored in Postgres (plan Q10b).

One row per PAUSE, not per run: a reject resumes the graph, the model may
call finalize_report again and pause again, and each of those pauses gets
its own decision. The rejection rate is per decision for the same reason -
per run, one run rejected twice then approved would count as "approved".

Lives in the checkpoint-postgres database next to the checkpoint tables:
paused_at has to survive an app restart, otherwise the wait time is lost
exactly when a restart happens between pause and decision.

Every function here is best-effort and never raises: a queue-bookkeeping
failure must not fail the request that paused or resumed a real run.
"""

import logging

log = logging.getLogger(__name__)

DECISIONS = ("approve", "reject")

SETUP_SQL = (
    """
    CREATE TABLE IF NOT EXISTS approval_requests (
        id          bigserial PRIMARY KEY,
        thread_id   text        NOT NULL,
        paused_at   timestamptz NOT NULL DEFAULT now(),
        decided_at  timestamptz,
        decision    text CHECK (decision IN ('approve', 'reject')),
        reason      text,
        CHECK ((decided_at IS NULL) = (decision IS NULL))
    )
    """,
    # At most one OPEN pause per thread: re-recording the same pause (e.g. a
    # retried request) is a no-op instead of a second row with a later
    # paused_at.
    """
    CREATE UNIQUE INDEX IF NOT EXISTS approval_requests_open_thread
        ON approval_requests (thread_id) WHERE decided_at IS NULL
    """,
)

# The table is created at API startup. CLI processes report the pending
# gauge too and never create it - check first rather than raise
# UndefinedTable every 5s.
TABLE_EXISTS_SQL = "SELECT (to_regclass('approval_requests') IS NOT NULL)::int"
PENDING_COUNT_SQL = "SELECT count(*) FROM approval_requests WHERE decided_at IS NULL"


def setup(pool) -> None:
    """Idempotent. Called at API startup, after the checkpointer's setup()."""
    with pool.connection() as conn:
        for statement in SETUP_SQL:
            conn.execute(statement)


def record_pause(pool, thread_id: str) -> None:
    try:
        with pool.connection() as conn:
            conn.execute(
                "INSERT INTO approval_requests (thread_id) VALUES (%s) "
                "ON CONFLICT (thread_id) WHERE decided_at IS NULL DO NOTHING",
                (thread_id,),
            )
    except Exception:
        log.warning("approval queue: recording pause failed", exc_info=True)


def record_decision(pool, thread_id: str, decision: str, reason: str | None) -> float | None:
    """Closes the thread's open pause. Returns seconds from paused_at to now
    (the database's clock for both ends, so app clock skew or a restart in
    between can't distort it), or None if there was no open pause row -
    e.g. the pause happened before this table existed."""
    try:
        with pool.connection() as conn:
            row = conn.execute(
                "UPDATE approval_requests SET decided_at = now(), decision = %s, reason = %s "
                "WHERE thread_id = %s AND decided_at IS NULL "
                "RETURNING EXTRACT(EPOCH FROM decided_at - paused_at)::float8 AS wait_seconds",
                (decision, reason, thread_id),
            ).fetchone()
        if row is None:
            log.warning("approval queue: no open pause for this thread", extra={"thread_id": thread_id})
            return None
        return row["wait_seconds"]
    except Exception:
        log.warning("approval queue: recording decision failed", exc_info=True)
        return None
