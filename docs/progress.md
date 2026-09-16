# docs/progress.md

## Current phase and branch
Phase: Review action plan — post-Phase-4 fixes
Branch: develop

## Steps status

### Done
- Step 14 — Self-host Langfuse
  - 6 services added to docker-compose.yml: postgres, redis, minio, clickhouse, langfuse-worker, langfuse-web
  - Verified: docker compose ps shows all healthy
  - Verified: auth_check() == True against http://localhost:3000
  - Verified: test trace visible in UI, trace_id 94cee9c1e78c60b907fb5aa5cd3199fa
  - .env updated: LANGFUSE_HOST=http://localhost:3000 (Cloud line removed), keys set, .env still gitignored
  - Merged: PR #6

- Steps 5, 24 — Identity/propagation gap
  - Root cause: IdentitySpanProcessor was registered in otel_setup.py but set_identity()
    was never called anywhere in the app, so session_id/user_id were always None
    on every span (matches the review finding: 0/71 spans had these fields)
  - Fix: call set_identity(session_id=thread_id) at start of /research and
    /approve endpoints in main.py, reset_identity() in a finally block
  - Verified: real request sent, Tempo trace queried directly (trace_id
    7640de9652148bac5e4cf24e5637635a) - session_id confirmed present on
    LangGraph, model, ChatDeepSeek, and 3 middleware spans
  - KNOWN REMAINING GAP (not hidden): FastAPI HTTP root span and its ASGI
    receive/send sub-spans do NOT carry session_id, because FastAPIInstrumentor
    starts that span before set_identity() runs inside the route handler body.
    Would need identity set in a middleware (before span creation) to fully fix.
    Not yet done - flagged for follow-up, not claimed as solved.
  - Merged: PR #9

## Housekeeping done alongside Step 14
- [x] Removed checkpoints.sqlite-shm / checkpoints.sqlite-wal from git tracking, added to .gitignore (PR #7)

## Not yet started (per suggested order of attack)
- Steps 12, 20, 21, 30 — small concrete bugs (NEXT UP)
  - Step 12: MODEL_PROFILE validation - commit fbcdf08 claims this is fixed,
    NOT YET independently re-verified with fresh test
  - Step 20: setup_otel_instrumentation() idempotency - commit fbcdf08 claims
    this is fixed, NOT YET independently re-verified
  - Step 21: OTEL_EXPORTER_OTLP_ENDPOINT load-order bug - not yet checked
  - Step 30: two FastAPI response bugs (text blocks -> 500, pending interrupt
    reported as completed) - not yet checked
- Step 18 — Run remaining 8/10 dataset prompts, rewrite findings (unblocked by Step 14, not started)
- Steps 15, 16, 26 — Langfuse-dependent verification, not started
- Step 22, 25, 28, 32 — missing demonstrations, not started
- Documentation corrections (Step 2, Step 5 doc, README Phase 4 claim) — not started
- Step 9 — Postgres deferral decision — not started

## Blockers / open decisions
- Commit fbcdf08 (already on develop before this review cycle) claims to address
  MODEL_PROFILE validation and idempotent otel setup, among other things.
  These specific claims (Step 12, Step 20) still need fresh independent
  verification before being trusted or marked done - this is next up.
- FastAPI root-span identity gap (see Steps 5/24 above) needs a decision:
  fix now via middleware, or document as accepted limitation for this phase.
