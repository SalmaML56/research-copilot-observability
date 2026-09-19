# Step 9 - Postgres Checkpointing Deferral Decision (Explicit)

Per the review: "either implement Postgres + demonstrate
resume-after-process-restart, OR explicitly re-document the deferral
decision (this project has deferred Postgres before, to Phase 7 - check
docs/ for that prior decision and make sure it's still explicit here, not
silently hidden behind a 'Phase 1 complete' label)."

## Decision: Deferred to Phase 7 (documented explicitly here)

The current checkpointer (`checkpointed_agent.py`) uses `SqliteSaver`.
Postgres-backed checkpointing is NOT implemented as of this writing.

## Why this is not a shortcut

The original project brief itself places Postgres checkpointing in
**Phase 7 (Production Hardening), Step 46**: "Deploy on LangGraph Server
(self-hosted) with Postgres checkpoints and streaming." SQLite was always
the intended Phase 1 choice; Postgres was always planned for Phase 7, not
skipped from Phase 1's original scope.

The gap the review correctly flagged was not that Postgres is
missing right now - it's that this deferral had never been written down
anywhere. It had only existed implicitly (by virtue of Phase 7 not being
reached yet) and risked being silently forgotten behind a "Phase 1
complete" label, exactly the pattern this whole review was about.

## Current state (explicit, so it can't be silently lost again)

- Checkpointer: `SqliteSaver`, file-based (`checkpoints.sqlite`)
- Works correctly for local development and demos (verified across this
  entire review cycle - human-in-the-loop pause/resume, Step 18's 10/10
  dataset prompts, multiple Langfuse/Phoenix/Grafana comparison runs)
- Does NOT provide: concurrent-safe multi-process access, production-grade
  durability guarantees, or the resume-after-process-restart guarantee a
  production deployment needs

## What needs to happen before Postgres implementation (Phase 7 scope)

1. Add a dedicated Postgres service (or reuse the existing
   `langfuse-postgres` service with a separate database/schema - needs a
   decision at that time)
2. Install `langgraph-checkpoint-postgres`
3. Swap `SqliteSaver` for `PostgresSaver` in `checkpointed_agent.py` (and
   `studio_agent.py` if Studio should also use Postgres in production)
4. Verify resume-after-process-restart works: start a run, pause it
   (human-in-the-loop interrupt), kill the process entirely, start a new
   process, resume the same thread ID, confirm it picks up correctly
5. This work belongs with the rest of Phase 7 (Steps 44-48: sampling,
   redaction, LangGraph Server deployment, load testing) since Postgres
   checkpointing is specifically tied to that production-hardening
   context, not an isolated swap.

## Conclusion

Deferral confirmed and now explicit: Postgres checkpointing remains
correctly scoped to Phase 7, not implemented in this pass, and this
decision is documented rather than assumed or hidden.
