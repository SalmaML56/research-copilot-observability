# Step 43 — Human Feedback (Thumbs Up/Down) — Findings

Added `POST /research/{thread_id}/feedback` to `api/main.py`: takes
`{"thumbs_up": true|false}` on a thread that has already produced a
completed response, and pushes it as a `user_feedback` score (Langfuse
`data_type="BOOLEAN"`) onto that response's own trace.

## Why this needed a new piece of state, not just `trace.get_current_span()`

Every other score-writer in this codebase (`score_ab_runs.py`,
`score_online.py`) runs in the same process/request that produced the
trace, so `trace_id` is always the *current* span. Feedback is structurally
different: it arrives on a **separate** HTTP request, placed by a human
after reading the answer, arbitrarily later than the request that produced
it. By then the original span is closed and its trace_id isn't recoverable
from `trace.get_current_span()` — a new root span exists for the feedback
request itself, with its own, different trace_id.

Fix: persist `trace_id` keyed by `thread_id` (the id the client already
holds, since it needed it for `/approve`) at the moment a response actually
completes — `_record_completed_trace()`, one small JSON file per thread
under `data/eval_results/completed_traces/`, same shape as the existing
`ONLINE_PENDING_DIR` pattern Step 40 already established. `research()` and
`approve()` both write it on their `status="completed"` branch (whichever
one actually produces the answer — per Step 40's finding, that's almost
always `approve()`, since `LEAD_AGENT_SYSTEM_PROMPT` requires approval
before every `finalize_report`). `ResearchResponse` also now returns
`trace_id` directly, so a client that keeps its own state doesn't need the
lookup at all.

## Verification — real server, real requests, real Langfuse query

Ran `uvicorn research_copilot.api.main:app` locally and drove it with real
HTTP requests, not a mocked client:

1. **404 path** — `POST /research/nonexistent-thread-id/feedback` →
   `404 {"detail":"No completed response found for this thread_id."}`.
   Confirms feedback correctly refuses to score a thread with no completed
   response, rather than silently no-op'ing or scoring the wrong trace.
2. **Real end-to-end flow** — `POST /research` with topic "What is the
   boiling point of water at sea level?" → `paused_for_approval` (expected,
   confirms `trace_id: null` on a non-completed response) → `POST
   /research/{thread_id}/approve` → `completed`, with a real answer and
   `trace_id: "eedaa26b25cb367decbe4df6f791f55b"`.
3. **Thumbs up** — `POST .../feedback {"thumbs_up": true}` → `200
   {"recorded": true}`. Verified **in Langfuse's own storage**, not just
   trusted from the HTTP 200: queried the `scores` table directly in the
   `langfuse-clickhouse` container (same verification method Step 42 used,
   since the REST `/api/public/scores` endpoint 404s on this v4
   events-only deployment) — `user_feedback`, `value=1`,
   `string_value="True"`, `data_type="BOOLEAN"` present against that exact
   trace_id.
4. **Thumbs down** — same thread, `{"thumbs_up": false}` → confirmed as a
   second, independent row: `value=0`, `string_value="False"`, later
   timestamp. Not a bug that both coexist — Langfuse scores are append-only
   by design (each call gets a new `score_id`); a real product would
   either overwrite by passing a fixed `score_id` or treat the latest by
   timestamp as authoritative, neither implemented here since the task
   only asked for "a way to post" feedback, not a revision policy.
5. **On-disk state** — `data/eval_results/completed_traces/<thread_id>.json`
   confirmed written with the correct trace_id after the real `/approve`
   call. Cleaned up after the test (gitignored path, same as
   `online_pending/`).

## Real finding — the ingestion delay, and the same pre-existing gap Step 40 hit

**Ingestion delay:** the thumbs-up score was not yet queryable in
ClickHouse immediately after the feedback endpoint's `client.flush()`
returned — a first query came back empty, a second query ~8s later found
it. `flush()` only guarantees the SDK delivered the score to the Langfuse
server; ClickHouse ingestion on this self-hosted deployment happens on its
own async schedule after that. Not a bug in this endpoint, but relevant if
anything ever needs to read feedback back immediately after posting it
(nothing currently does).

**Same gap as Step 40, re-confirmed here:** queried the `traces` table for
this exact trace_id — **zero rows**. The score is real and correctly
attached, but there is no corresponding Langfuse trace document to attach
it to, because `api/main.py`'s agent path never runs Langfuse's
`CallbackHandler` (it only uses OTel instrumentation, which exports to the
Collector → Grafana path, not to Langfuse). This means a `user_feedback`
score posted through this endpoint will show up in Langfuse as a score
against a trace_id with no visible trace content in the UI — functionally
fine for `create_score` (already established in Step 40 that Langfuse
doesn't validate trace existence the way `comments.create` does), but
worth stating plainly rather than implying the Langfuse UI will show a
nice linked "thumbs up" on a browsable trace. Fixing this (wiring
`get_langfuse_handler()` into the live API's agent config, the way
`main_agent.py`/`run_eval_batch.py` already do for offline runs) is a
real, scoped follow-up, not attempted here — same reasoning as Step 42's
model-config boundary: changing the live agent's callback wiring is a
bigger change than "add a feedback endpoint" and affects every request,
not just this feature.

## Files involved

- `src/research_copilot/api/main.py` — this step (new endpoint + models +
  `_record_completed_trace`/`_get_completed_trace`, `trace_id` added to
  `ResearchResponse`, `_current_trace_id()` extracted from the existing
  Step 40 inline extraction, no behavior change to Step 40's code path)
