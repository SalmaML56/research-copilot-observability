# Phase 7 plan — production hardening (REGENERATED)

> **Regenerated 2026-09-23.** The first version of this plan was only ever
> shown in chat. It was never saved and was lost in transit. This is a new
> version, not a recovered copy. The investigation was redone from scratch
> against the current repo and containers (rule 1). The four findings the
> first version is known to have had were each re-checked here against
> real code or commands:
> tail-sampling pipeline split (§44), sync `PostgresSaver` (§46),
> connection pooling (§46), missing reject endpoint (§48).
>
> Rules: `docs/project_instructions.md`. Requirements:
> `docs/all_phases_original_plan.md` (Phase 7, Steps 44–48).
> Branch: `phase-7/production-hardening`, cut from `develop` at `9ed4da5`.

**Status:** plan only. No code written. Blocked on the open questions at
the end.

## Decisions (answered 2026-09-23)

| Q | Answer |
|---|---|
| Q1–Q5 | *pending* |
| Q6 | (b) keep or drop per session, via a deterministic flag from a hash of `session_id` |
| Q7a | Yes: redaction is on by default in prod. Unredacted full capture is the per-env opt-in |
| Q7b | (a) collector traces + logs only. Checkpoint DB, eval files and direct-Langfuse mode documented as gaps. `debug` exporter off outside dev |
| Q8 | (c) stub model for the 20-session leakage test + ~5 real DeepSeek runs. Reason: repeated Codespace interruptions during long runs, and to keep cost/time controlled |
| Q9 | (a) bypass: load-test sessions are always kept |
| Q10a | (a) reject with optional reason |
| Q10b | (a) `paused_at` in a Postgres table |
| Q11 | Order 46 → 44 → 45 → 48 → 47 approved |
| Q12 | (a) + (b): Postgres table-size gauge + alert (e) updated; pending-approval gauge from a DB query |
| Q13 | Yes. Done in `06d6865` |

---

## Verified current state (evidence for everything below)

| Fact | How verified |
|---|---|
| Collector `0.159.0` ships `tail_sampling`, `redaction`, `forward`, `routing`, `filter`, `memory_limiter` | `docker run --rm otel/opentelemetry-collector-contrib:0.159.0 components` |
| Collector `traces` pipeline has `span_metrics` as an **exporter**, next to `otlp_http/grafana` and `debug` | `collector/otel-collector-config.yaml` |
| `debug` exporter runs at `verbosity: detailed` on traces **and** logs | same file |
| Collector container has `mem_limit: 512m` | `docker-compose.yml` |
| API endpoints are sync `def`. Agent calls are sync `agent.invoke()`. A **new** `SqliteSaver.from_conn_string()` is opened on every request | `src/research_copilot/api/main.py` |
| Only `/research`, `/approve`, `/feedback`, `/health` exist. **No reject endpoint** | same file |
| `interrupt_on={"finalize_report": True}` resolves to allowed decisions `approve, edit, reject, respond` | installed `langchain/agents/middleware/human_in_the_loop.py` |
| Reject **with** a message → tool gets `"User rejected … with reason: …"` and the model keeps going (may re-call `finalize_report`). Reject **without** a message → `"… Do not retry this tool call unless the user explicitly requests it."` | same file, `_process_decision` |
| `langgraph-checkpoint-postgres` latest = `3.1.2` (needs `psycopg>=3.2`, `psycopg-pool>=3.2`) | throwaway `uv run --no-project --with …` env, project untouched |
| `PostgresSaver.from_conn_string()` opens **one plain `Connection`** (`autocommit=True, prepare_threshold=0, row_factory=dict_row`), with **no pool**. `PostgresSaver(conn)` also accepts a pool | `inspect.getsource` in that env |
| `langfuse-postgres`: `max_connections=100`, 9 in use (Langfuse), only DB is `postgres` | `psql` in the running container |
| `langgraph up` "For local dev, requires env var `LANGSMITH_API_KEY` with access to LangSmith Deployment. For production use, requires a license key in `LANGGRAPH_CLOUD_LICENSE_KEY`." It launches its own `langgraph-postgres` + `langgraph-redis` unless `--postgres-uri` is given | `langgraph_cli/cli.py`, `docker.py` (CLI 0.4.31) |
| **No** `LANGSMITH_*` / `LANGGRAPH_*` key in `.env` | `grep` (names only, no values printed) |
| `studio_agent.py` (the graph `langgraph.json` serves) has **no** OTel/metrics/identity setup. All of that lives in the FastAPI app | file read |
| Checkpoint-size gauge and alert (e) read the **SQLite file** size | `metrics_setup.py::_observe_checkpoint_db_size`, `research-copilot-alerts.yaml` rc-p5-checkpoint-growth |
| `checkpoints.sqlite` is **227 MB** today. Alert (e)'s comment assumed ~13.7 MB | `ls -la` |
| Pending-approval gauge is an in-process `set`, reset on restart | `metrics_setup.py` |
| Identity propagates via `contextvars.ContextVar` | `observability/identity.py` |
| OpenInference `TraceConfig` supports `hide_inputs`, `hide_outputs`, `hide_input_messages`, … | `inspect.signature` |
| `tests/` is empty (`.gitkeep` only) | `ls` |
| Currently running: only the six Langfuse containers. `otel-collector`, `grafana-lgtm` and `phoenix` are down | `docker ps` |

---

## Step 44 — Tail sampling (100% errored/expensive, 20% of the rest)

**Build:** add a `tail_sampling` processor to the collector with three
policies: `status_code: ERROR`, an "expensive" policy (definition = **Q5**),
and `probabilistic: 20%`.

**Key architectural finding: the traces pipeline must be split.**
`span_metrics` is currently an exporter of the same `traces` pipeline that
would get `tail_sampling`. If sampling goes into that pipeline, the RED
metrics (p50/p95, tool error rate, every Step 35/36 panel and alert) get
computed from the ~20% sample. Worse, the sample is biased: 100% of errors
are kept but only 20% of successes, so the tool **error rate would read up
to ~5x too high**. The fix:

```
traces/in:      otlp → gen_ai_normalizer → transform/cost → [redaction, §45]
                → exporters: span_metrics, forward/sampling
traces/sampled: forward/sampling → tail_sampling → exporters: otlp_http/grafana (+ debug in dev)
```

`span_metrics` sees 100% of spans. Only trace **storage** is sampled.
`gen_ai.client.*` metrics come from the app's own MeterProvider, not
spans, so they're unaffected either way.

**Risks:**
- **One run = several traces.** `/research` and `/approve` are separate HTTP
  requests, so separate traces. Independent 20% sampling keeps both halves
  of a successful run only ~4% of the time → **Q6**.
- **`decision_wait` vs run length.** Agent runs take minutes (LLM timeout is
  90s × retries). The HTTP root span ends **last**, and its error status
  arrives last. If `decision_wait` is shorter than a run, the decision is made
  on a partial trace. Late spans need the decision cache. Exact config keys
  get checked against the 0.159.0 docs before writing.
- **Memory.** Tail sampling buffers every span for `decision_wait`. Spans are
  large (attribute limit raised to 2048, full message content), and the
  collector is capped at 512 MB. Add `memory_limiter` and watch it under
  the Step 47 load.

**Verify:** real runs, not config review. (1) Force an error (e.g. an
invalid model key on one request) → the trace is in Tempo. (2) An expensive
run → in Tempo. (3) N normal runs → roughly 20% in Tempo (small N, so
report the actual count, not "≈20%"). (4) The `span_metrics` request count
in Prometheus equals N (proves the split). Collector's own
`otelcol_processor_tail_sampling_*` metrics as supporting evidence.

## Step 45 — Redact sensitive content (emails, phones, keys)

**Build:** a `redaction` processor in `traces/in` (and the logs pipeline),
**before** the sampling fork and before any exporter. It masks regexes for
email, phone, API-key shapes (`sk-…`, `pk-lf-…`, bearer tokens). Per-environment
switch via env var + collector config (semantics = **Q7**).

**Risks and real gaps found:**
- `debug` exporter at `verbosity: detailed` prints every attribute
  (all prompts and answers) to the collector's container log. That's a
  leak regardless of redaction placement. It must sit after redaction, or be
  dropped outside dev.
- **Things the collector can't redact**, which must at least be documented:
  (a) checkpoint DB rows (full message history, in Postgres after §46);
  (b) `data/eval_results/*` online-sample files (raw prompt + answer);
  (c) `TRACING_BACKEND=langfuse|both` exports straight to Langfuse,
  bypassing the collector. Scope = **Q7**.
- Regex over-matching: phone patterns hit numbers in research content (years,
  figures). Test against real captured spans, not just synthetic strings.

**Verify:** send a real request whose topic contains a fake email/phone/key.
Show the Tempo span attributes and Loki log line with the values masked.
Flip the env to full-capture and show them present. Also check the
collector's debug output.

## Step 46 — LangGraph Server + Postgres checkpoints + streaming

The riskiest step: it touches core checkpointing.

**Build (FastAPI path, needed in every Q1 option except "Server only"):**
1. Postgres service per **Q3**.
2. `uv add langgraph-checkpoint-postgres "psycopg[binary,pool]"`.
3. Replace `SqliteSaver` with `PostgresSaver` in `checkpointed_agent.py` and
   `api/main.py`, with the connection string from env (`CHECKPOINT_DB_URI`).
4. One-time `checkpointer.setup()` to create the tables.

**Decision: sync `PostgresSaver`, not `AsyncPostgresSaver`.** Every
endpoint is sync `def` and every call is sync `agent.invoke()`. Going async
means rewriting all three endpoints to `async def` + `ainvoke`, and the
sync `get_state` calls too. That turns a checkpointer swap into a
concurrency-model change inside the riskiest step. Sync keeps the change
to the checkpointer only. FastAPI already runs sync endpoints on its
threadpool (default 40 threads, which covers 20 concurrent sessions).

**Connection pooling concern.** The current pattern opens a checkpointer
**per request**. `from_conn_string` = one new Postgres connection per
request (verified from source), plus TCP/auth setup each time. Under
Step 47's 20 concurrent sessions that's 20+ short-lived connections
against a server with 91 free slots, shared with Langfuse. It also
throws away reuse. Plan: one process-wide
`psycopg_pool.ConnectionPool(kwargs={autocommit: True, prepare_threshold: 0, row_factory: dict_row})`,
opened in FastAPI's lifespan, with `PostgresSaver(pool)` built once. The
kwargs must match what `from_conn_string` sets, or the saver breaks.
Pool size is explicit (e.g. max 20) so it can't exhaust `max_connections`.

**Streaming:** today nothing streams. The API uses `invoke`. Either
add an SSE endpoint to FastAPI (`agent.stream(..., stream_mode=…)`), or use
LangGraph Server's built-in streaming. Depends on **Q1**.

**LangGraph Server:** `langgraph up` needs `LANGSMITH_API_KEY` (not
present) and brings its own Postgres + Redis. The graph it serves
(`studio_agent.py`) has **none** of the Phase 3–6 observability
(OTel spans, identity, metrics). A Server deployment would be un-observed
unless that's added → **Q1/Q2**.

**Other breakage the swap causes:**
- Checkpoint-size gauge + alert (e) measure the SQLite file. After the swap
  they'd silently report the stale file forever → **Q12**.
- Existing 227 MB `checkpoints.sqlite` threads → **Q4**.

**Verify (exactly the brief's test, with real processes):** start
uvicorn → `POST /research` → confirm `paused_for_approval` → `kill -9`
the uvicorn PID → start a **new** process → `POST /approve` with the
same `thread_id` → `completed` with an answer. Plus `psql` showing rows in
`checkpoints` for that thread before and after. Also run the CLI path
(`checkpointed_agent.py`) the same way.

## Step 47 — Load test, 20 concurrent sessions, no cross-session leakage

**Build:** `scripts/load_test.py` (httpx 0.28.1 already installed). It fires
20 concurrent `/research` requests, each with a unique `thread_id` +
`user_id`, then approves each one. It records thread_id → trace_ids.

**Leakage check (automated, not eyeballed):** for each trace in Tempo,
every span's `session_id` must equal the one session that trace belongs
to, and no `session_id` may appear in another session's traces. Also
check the checkpoint rows per `thread_id` for the same property.

**Risks:**
- Tail sampling would drop ~80% of the traces the check needs → **Q9**.
- Cost/rate limits of 20 real concurrent agent runs → **Q8**. (Groq free
  tier already failed at 8000 TPM in Step 42.)
- Identity is a `ContextVar`. Sync endpoints run in threadpool threads.
  This is exactly what the test is designed to prove, so it isn't assumed
  safe.
- Should run **after** §46: SQLite under 20 concurrent writers would test
  the wrong system.

**Verify:** script output (20/20 completed or the real failure list),
the leakage checker's per-session table, and the collector memory during
the run.

## Step 48 — Human-in-the-loop approval queue metrics

**Build:** (1) `POST /research/{thread_id}/reject` (optional reason,
semantics = **Q10**). It's needed because a rejection rate can't be measured
while rejection is impossible through the API. (2) record `paused_at` per
thread. (3) on approve/reject: histogram
`research_copilot.approval.wait_seconds{decision}` + counter
`research_copilot.approval.decisions{decision}`. (4) dashboard panels:
p50/p95 wait, rejection rate = reject / (approve + reject).

**Risks:**
- `paused_at` must survive a restart, or the wait time is lost exactly
  when a restart happens. Source = **Q10**.
- A reject resumes the graph: the model runs again and may pause again.
  So "rejection rate" must be per **decision**, not per run, or it's
  miscounted.
- The pending-approval gauge resets on restart (already documented).
  With Postgres it could become a DB query → part of **Q12**.

**Verify:** real runs, some approved and some rejected after a known
wait. Show the Prometheus values match the known waits/decisions. Restart
between pause and approve and show `wait_seconds` is still correct.

---

## Proposed order: 46 → 44 → 45 → 48 → 47

- **46 first:** the riskiest, and everything else sits on top of it. Load-testing
  SQLite would be meaningless, and 48's `paused_at` store may live in Postgres.
- **44 then 45:** both edit the same collector file. 44 creates the pipeline split
  that 45's redaction slots into (before the fork).
- **48 before 47:** the load test should exercise the final API, reject
  endpoint included, and the final pipeline.
- **47 last:** it's the integration test of everything above.

Deviates from numeric order. Confirm in **Q11**.

---

## Open questions (need answers before any code)

**Q1. What does Step 46 actually deploy?**
- (a) Both: FastAPI + `PostgresSaver` stays the primary, observed app, and
  `langgraph up` is also brought up against the same Postgres as a
  demonstrated deployment (its observability gap documented or closed).
- (b) LangGraph Server only: retire the FastAPI path. Loses or rebuilds all
  Phase 3–6 observability hooks (identity, metrics, online evals, feedback).
- (c) FastAPI + `PostgresSaver` only, plus an SSE streaming endpoint. Skip
  LangGraph Server and document why (licence/LangSmith dependency).
- *Recommendation:* (a) if a LangSmith key is available (Q2), else (c).

**Q2. LangSmith API key for `langgraph up`.**
- (a) You'll create one (LangSmith account; the Server validates against
  LangSmith). I'd set `LANGSMITH_TRACING=false` so traces don't also go to
  LangSmith.
- (b) No key → Q1 can't be (a) or (b).

**Q3. Which Postgres holds the checkpoints?**
- (a) New dedicated `checkpoint-postgres` service (own volume, own port such
  as 5433). Isolated from Langfuse's connections, upgrades and backups.
- (b) Reuse `langfuse-postgres` with a separate `checkpoints` database.
  One less container, but shares its 100 connections and lifecycle.
- *Recommendation:* (a).

**Q4. Existing 227 MB `checkpoints.sqlite`.**
- (a) Start fresh in Postgres, leave the SQLite file untouched on disk.
- (b) Migrate only currently paused threads.
- (c) Migrate everything.
- *Recommendation:* (a). It's demo/eval history, and migration is its own
  risk.

**Q5. What counts as an "expensive" run for sampling?** The collector
can't sum cost across a trace. `cost_usd` only exists on individual model-call
spans.
- (a) Any single model-call span with `gen_ai.usage.cost_usd` > $X.
- (b) Trace duration > N seconds (`latency` policy).
- (c) Span count > N (`span_count` policy, a proxy for runaway runs).
- (d) A combination. And what thresholds? (I'd propose numbers from the
  existing Step 38/42 data for you to approve.)

**Q6. Sampling unit: trace or session?** A run is ≥2 traces (`/research`,
`/approve`).
- (a) Accept per-trace sampling: halves of the same run get sampled
  independently.
- (b) Keep-or-drop per session: the app computes a deterministic keep flag
  from a hash of `session_id`, stamps it on spans, and the tail policy
  keeps on that attribute. All traces of a run are kept or dropped together.
- *Recommendation:* (b).

**Q7. Redaction semantics and scope.**
- 7a. Meaning of "opt-in per environment, off by default in prod". My
  reading: **full (unredacted) capture** is the opt-in, so redaction is
  **on** by default in prod and full capture can be enabled per env
  (e.g. in dev). Correct?
- 7b. Scope:
  - (a) collector traces + logs only, and the gaps (checkpoint DB, eval
    files, direct-Langfuse mode) documented;
  - (b) (a) plus app-side OpenInference `TraceConfig` hiding;
  - (c) also redact what's written to eval files.
  - *Recommendation:* (a), plus dropping the `debug` exporter outside dev.

**Q8. Load-test model and budget.**
- (a) 20 real DeepSeek runs (real cost, estimated from Step 42 data before
  running).
- (b) Groq cheap profile (known to hit the 8000 TPM free-tier limit).
- (c) A fake/stub chat model for the 20-way leakage test, plus a small
  real batch (e.g. 5).
- *Recommendation:* (a) if the cost is acceptable, else (c).

**Q9. Sampling during the load test.** The leakage check needs every trace.
- (a) An env/attribute bypass that keeps 100% for load-test sessions
  (e.g. `load_test=true` → always keep).
- (b) Temporarily run the collector without tail sampling for Step 47.
- (c) Check only the sampled traces.
- *Recommendation:* (a). It tests the real pipeline.

**Q10. Approval-queue details.**
- 10a. Reject semantics:
  - (a) reject with optional reason: with a reason, the model may retry;
    without one, it's told not to;
  - (b) reject always without a reason (hard stop);
  - (c) reject with reason required.
- 10b. Where `paused_at` lives:
  - (a) a small Postgres table (survives restarts, same DB as checkpoints);
  - (b) a per-thread JSON file like the existing `completed_traces` pattern;
  - (c) derived from checkpoint timestamps.
  - *Recommendation:* (a).

**Q11. Order 46 → 44 → 45 → 48 → 47 instead of numeric?** Yes / numeric
order / other.

**Q12. Checkpoint-DB metrics after the swap.**
- (a) Replace the SQLite file-size gauge with a Postgres
  `pg_total_relation_size` query over the checkpoint tables, and update
  alert (e) and its threshold.
- (b) Also move the pending-approval gauge to a DB query (fixes the
  restart-reset gap).
- (c) Leave both as they are and document.
- *Recommendation:* (a) + (b).

**Q13 (housekeeping).** `docs/all_phases_original_plan.md` still says
Phase 6 "IN PROGRESS". Update it to DONE in a separate small commit?
