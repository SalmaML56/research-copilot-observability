# docs/progress.md

## Current phase and branch
Phase: Ali's review action plan — post-Phase-4 fixes
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

### In progress
(none)

### Not started
- Step 18 — Run remaining 8/10 dataset prompts, rewrite findings (now unblocked)
- Steps 5, 24 — identity/propagation gap
- Steps 12, 20, 21, 30 — small concrete bugs
- Steps 15, 16, 26 — Langfuse-dependent verification
- Steps 22, 25, 28, 32 — missing demonstrations
- Documentation corrections (Step 2, Step 5 doc, README Phase 4 claim)
- Step 9 — Postgres deferral decision

## Blockers / open decisions
- Commit fbcdf08 (already on develop before this review cycle) claims to address
  MODEL_PROFILE validation, .env.example fixes, identity propagation, and idempotent
  otel setup. Not yet individually re-verified with fresh output against Steps 5, 6,
  12, 20, 24. Do not mark those steps done until verified.
