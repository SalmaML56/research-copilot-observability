# docs/progress.md

## Current phase and branch
Phase: 6 — Evaluation framework (IN PROGRESS, 2026-09-22)
Branch: phase-6/evaluation-framework

## Phase 6 — Evaluation framework — IN PROGRESS (2026-09-22)

- Step 38 — offline eval data capture. `capture_runs.py` runs dataset
  prompts through the live agent and saves answer/retrieval_context/
  tool_calls/trace_id per prompt to `data/eval_results/step38_runs.jsonl`.
  5 of the 25-prompt dataset (rc-001–rc-005) captured — enough to
  demonstrate the framework, by explicit scope decision, not the full set.
  All 5 have `status: "ok"`.
- Step 39 — offline eval scoring. `score_runs.py` scores each row with
  DeepEval (`GroqJudge`, `openai/gpt-oss-120b`) on correctness
  (`GEval` vs. `expected_facts`) and faithfulness (`FaithfulnessMetric` vs.
  `retrieval_context`), writes `data/eval_results/step39_scores.jsonl`, and
  pushes both scores onto each row's Langfuse trace. Required capping
  context/answer text fed to the judge and retrying transient Groq errors
  to work within the Groq free tier's 8000 TPM limit — see inline comments
  in `score_runs.py`.
  **Real finding, not a scoring bug:** 3 of 5 runs (60%) scored
  correctness=0.00 despite capture `status: "ok"` — the lead agent gave up
  after the researcher subagent's `write_file` succeeded but its own
  `read_file` on the same path found nothing, the exact failure mode Step
  18 Finding 3 bounded (capped retry, no hang) but never root-caused.
  Faithfulness stayed 1.00 across all 5, so correctness was the only metric
  that caught it. Documented, not investigated further (out of scope for
  Phase 6): `docs/step38_39_findings.md`.
- Step 40 — online evals on ~10% of live runs. DONE: capture mechanism and
  scorer both built and verified against real live traffic.
  The originally planned design — a decoupled scorer pulling sampled trace
  content back out of Langfuse after the fact — turned out not to be
  possible on this self-hosted deployment: verified directly against the
  running instance that `trace.list`/`trace.get` 404 (Langfuse v4
  "events_only" mode disables them), and `observations.get_many` returns
  every observation's `input`/`output` as `None` regardless of requested
  fields. `create_score(trace_id=...)` does work (same as Step 39 already
  relies on). So capture happens inline instead: `api/main.py`'s
  `/research` handler samples ~10% of requests (`random.random() < 0.1`,
  decided before any collector/callback cost is paid — the other 90% pay
  nothing extra) and attaches the same `ToolCollector` Step 38 uses
  (extracted to `evals/tool_collector.py`, shared by both).
  **Second real finding, caught by smoke-testing before commit, not by
  code review:** `LEAD_AGENT_SYSTEM_PROMPT` requires human approval before
  every `finalize_report`, so `research()` essentially never returns
  `"completed"` directly — confirmed live (4/4 smoke-test requests paused;
  the 2 that were approved completed via `/approve`, not `/research`). The
  first version of this capture only recorded on `research()`'s own
  completion, which would have captured zero samples on real traffic. Fixed
  with a pending-capture file per `thread_id`
  (`data/eval_results/online_pending/`), written when a sampled run pauses,
  consumed and finalized into `data/eval_results/online_samples.jsonl`
  (gitignored, same as Step 38/39's output) whichever request — `research()`
  or `approve()` — actually produces the completion.
  All capture-path code is wrapped to fail safe (warn-log, never raise) so
  a bug here can't break a real request; verified with a forced-failure
  test, not just by inspection.
  `score_online.py` reuses Step 39's DeepEval/GroqJudge core (extracted to
  a shared `evals/scoring_utils.py`, no behavior change to Step 39) on
  `AnswerRelevancyMetric` + `FaithfulnessMetric` — no `expected_facts`
  exist for arbitrary live topics, so relevancy stands in for Step 39's
  correctness. Verified against one genuinely captured live sample (added
  a `ONLINE_EVAL_SAMPLE_RATE` env override, default unchanged at 0.1, to
  force sampling for this one supervised test): relevancy 0.56 (pass, but
  notably not clean — the reason cites "unrelated historical verification,
  tool failures, and workflow steps" diluting the actual answer, a softer
  echo of Step 39's self-narration finding), faithfulness 1.00. Both scores
  independently confirmed present on the real Langfuse trace via a fresh
  API query (`scores_v3.get_many_v3`), not just trusted from the
  `create_score` call succeeding. Resume-on-rerun also verified (second run
  correctly skipped the already-scored row, no duplicate Langfuse writes).
- Step 41 — the failure-to-dataset loop (generic, reusable mechanism;
  rc-001/003/005 are the first real case flowing through it, not
  hardcoded). DONE.
  **Verified before building on it, same discipline as Step 40:**
  Langfuse-side trace tagging isn't viable here either -
  `comments.create` validates its target through the same lookup path
  `trace.list`/`trace.get` use, which events-only mode disables (404
  "Reference object, TRACE: ... not found", same root cause as Step 40).
  `dataset_items.create(..., source_trace_id=...)` does work and
  round-trips correctly (tested and cleaned up) - a viable Langfuse-native
  option, but not used here since Steps 38-40 already keep everything
  locally, so "identify failures" and "export" both reduce to reading
  `step39_scores.jsonl`/`online_scores.jsonl` and joining back to
  `step38_runs.jsonl`/`online_samples.jsonl` by id - no Langfuse read
  needed at all.
  `find_regressions.py` scans both scores files for sub-threshold rows,
  auto-drafts a `corrected_expectation` by asking `GroqJudge` to
  generalize its own failure reason into a reusable, topic-agnostic
  statement, and writes `data/regression_cases.jsonl` (git-tracked, same
  as `test_dataset.jsonl` - a curated artifact, not ephemeral run output)
  with `status="draft_needs_review"`. Nothing is auto-committed: real run
  found 3 failures (rc-001/003/005) and drafted 3 candidates, one of which
  (rc-001's) was close to right and two of which drifted toward
  restating "include all facts" - a real demonstration of why the human
  gate matters, not a hypothetical one. All 3 confirmed by hand with the
  same wording: "the agent must produce a substantive answer with actual
  facts, not a research-incomplete report, when the underlying
  search/research actually succeeded" - checked this premise against the
  real data first (all 3 had 36-41 genuine on-topic search results in
  `retrieval_context`, so "research actually succeeded" is factually
  grounded, not assumed).
- Step 42 - A/B test, frontier (DeepSeek `deepseek-chat`) vs. open-weight
  (Groq `openai/gpt-oss-20b`), same 5 prompts (rc-001-rc-005) as Steps
  38/39, same correctness/faithfulness metrics and judge so cost and
  quality sit on one scale. DONE (capture + score + comparison), but the
  intended cost/quality comparison itself did not complete as designed -
  see below.
  **Real finding, the headline result, not a footnote:** primary arm 5/5
  completed (mean cost $0.220759/run, mean correctness 0.46, mean
  faithfulness 0.99); cheap arm **0/5 completed** - every attempt errored
  on Groq's on-demand tier limits for `openai/gpt-oss-20b` (two distinct
  limits hit: `413` per-request 8000 TPM ceiling on rc-001/002, then a
  **daily** 200,000 TPD budget exhausted by rc-003/004/005, confirmed by
  the literal `Used 198204.../200000` climbing across those three errors).
  No cost/quality numbers exist for the cheap arm - nothing to average.
  Root cause not fixed (would mean changing the agent config specifically
  to make one A/B arm pass, undermining the comparison): full write-up,
  verbatim error text and the `compare_ab_runs.py` aggregate output in
  `docs/step42_ab_test.md`. Verification: scores confirmed landing in
  Langfuse by querying the `scores` table directly in the
  `langfuse-clickhouse` container (REST `/api/public/scores` 404s on this
  v4 events-only deployment, same constraint as Steps 40/41) for all 5
  primary trace IDs - all 10 rows (5 traces x 2 metrics) present.
- Step 43 - human feedback. Added `POST /research/{thread_id}/feedback`
  (`{"thumbs_up": bool}`) to `api/main.py`, pushing a `user_feedback`
  BOOLEAN score onto the completed response's trace. DONE, verified live.
  Needed a new piece of state, not just the current span's trace_id:
  feedback arrives on a separate later HTTP request after the original
  span has closed, so `trace_id` is persisted keyed by `thread_id`
  (`data/eval_results/completed_traces/`, same pattern as Step 40's
  `ONLINE_PENDING_DIR`) at the moment `research()`/`approve()` actually
  completes; `ResearchResponse` also now returns `trace_id` directly.
  Verified against a real running server: 404 on an incomplete thread,
  then a full real `/research` -> `paused_for_approval` -> `/approve` ->
  `completed` (real trace_id) -> `/feedback` thumbs-up and thumbs-down both
  confirmed landing in Langfuse by querying the `scores` table directly in
  `langfuse-clickhouse` (same method Step 42 used - REST `/api/public/scores`
  404s on this deployment).
  **Real finding, re-confirming Step 40's gap, not a new bug:** queried
  the `traces` table for the same trace_id - zero rows. The score is real
  and correctly attached, but `api/main.py`'s live agent path never runs
  Langfuse's `CallbackHandler` (OTel-only), so there is no Langfuse trace
  document behind it - the feedback score will show in Langfuse with no
  linked trace content in the UI. Also observed a ~8s async ingestion
  delay between `client.flush()` returning and the score being queryable
  in ClickHouse (Langfuse's own pipeline, not this endpoint). Full
  write-up: `docs/step43_human_feedback.md`.
  `score_regressions.py` scores only `status="confirmed"` entries (drafts
  are skipped even if someone forgets to gate them manually - verified
  this refusal directly: ran it against all-draft state first, got "0
  confirmed regression case(s) to score") with one generic `GEval`
  ("does actual output fulfill corrected_expectation") reusable across any
  future regression case regardless of topic. Real run against the 3
  confirmed cases: all 3 scored 0.00, correctly flagged as still-failing
  (the underlying bug is unfixed, per Step 39 - this proves the check
  would catch it, not that it's resolved). All 3 scores independently
  confirmed present on their real Langfuse traces via a fresh API query.
  Shares Step 39/40's rate-limit backoff via `scoring_utils.py`.

## Phase 5 — Metrics, dashboards, alerts — DONE (2026-09-21)

Full task list with per-task status: `docs/tasks-ph5.md`.
Short guide: `docs/phase5_evidence/README.md`.
Evidence (trace IDs, queries, 8 screenshots):
`docs/phase5_evidence/verification-details.md`.

Verified against the running stack — 9 containers, two real DeepSeek runs,
one taken all the way through `POST /research` → pause → `approve` →
completed (1641-char answer).

- Step 33 — token and duration metrics. **The brief's premise was wrong for
  this stack**: `openinference-instrumentation-langchain` emits traces only,
  never metrics, so neither `gen_ai.client.token.usage` nor
  `gen_ai.client.operation.duration` existed anywhere. They are now produced
  deliberately by `GenAIMetricsCallbackHandler`, and both are queryable in
  Prometheus. Written up in `docs/step33_metrics_verification.md`.

- Step 34 — cost. Computed in the Collector per model-call span, as
  `gen_ai.usage.cost_usd`. Model-aware (4 models; unknown models marked
  `unpriced`, never $0). Rates, sources and as-of date:
  `docs/step34_cost_model.md`. Arithmetic checked by hand against a live
  span — exact to 8 decimal places. Never copied onto parent spans: 26 cost
  spans = 26 token spans = 26 model spans on the verification trace.

- Step 35 — one dashboard, provisioned from git, 9 panels, all showing real
  data. Survives container recreation.

- Step 36 — five alert rules, provisioned as YAML. One
  (**cost spiked 5x**) observed in the `Firing` state on real traffic, not a
  synthetic trigger.

- Step 37 — structured JSON logs with trace context. The codebase had no
  `logging` usage at all before this. Logs reach Loki via a new Collector
  logs pipeline, and correlation was clicked through **in both directions**
  in the browser: Loki log line → its trace in Tempo, and Tempo span →
  "Explore the logs for this in split view" → 19 matching log lines.

### Pre-existing bugs that had to be fixed before any Phase 5 number was trustworthy

- **Span attribute limit** (review v2, Addendum C). The SDK default of 128
  attributes/span was overflowing on long-context model spans, and the SDK
  evicts the *oldest* attributes first — so identity was the first thing
  discarded, on exactly the most expensive calls. `SpanLimits(
  max_span_attributes=2048)`. After: 0 spans with dropped attributes on a
  202-span run, 199/202 carrying `session_id`.

- **Langfuse `@observe` double-export** (review v2, Step 17 / Addendum D).
  Every tool call was exported twice — 74 `web_search` spans for 37 real
  HTTP calls, plus 224 stray `langfuse.*` attributes in Tempo. Now gated
  behind `TRACING_BACKEND` (default `otel`). After: 0 `langfuse.*`
  attributes, one span per tool call. Every tool panel and the tool-error
  alert were 2x wrong until this landed.

- **Span status** (review v2, Step 24). Failed tool attempts were `UNSET`,
  never `ERROR` — 0 ERROR spans out of 78 UNSET. A tool-failure-rate alert
  on that data would have read 0% forever. Now 5 ERROR / 23 OK on a real
  run; the real rate in this environment is 17.9%.

- **FastAPI root span identity** (review v2, Steps 5/24/30). Now stamped
  directly on the still-open root span in the handler. Still not covered:
  the 3 ASGI `http send`/`http receive` sub-spans, which are framework
  plumbing created outside the handler body — stated, not hidden.

- **`user_id` hardcoded `"unknown"`** (review v2, Step 24). The API now
  accepts a `user_id`, which is what makes the per-user cost alert
  meaningful rather than environment-wide dressed up as per-user.

- **Langfuse not reproducible** (review v2, Addendum A). `LANGFUSE_INIT_*`
  now provisions an org, project, user and API keys on first start, sourced
  from `.env` so the app's keys and Langfuse's keys cannot drift apart.
  Verified by API auth and by signing into the UI.

- **`grafana-lgtm` had no volume at all.** Every dashboard, alert rule and
  stored trace was lost on restart. Now four named volumes; verified by
  removing and recreating the container.

- **`.env` load order in `otel_setup.py`** (review v2, Step 21) and the
  checkpoint-DB gauge's relative path — both fixed.

### Found only by querying the backends (not predicted by the plan)

1. OTel unit `"1"` becomes a `_ratio` suffix in Prometheus, so
   `research_copilot.runs.pending_approval` arrived as
   `..._pending_approval_ratio`. Fixed with annotation units.
2. The token metric was labelled with the *configured* model name
   (`deepseek-chat`) while the cost attribute was keyed on the
   *provider-reported* one (`deepseek-flash`). Any panel joining them would
   have matched nothing. Fixed by reading the name off the response.
3. `spanmetrics` → `span_metrics` and `otlphttp` → `otlp_http` are
   deprecated aliases in Collector 0.159.0.
4. A single-file bind mount is unsafe on Docker Desktop for Windows — a
   missing host file becomes a *directory* and every later start fails.
5. `LANGFUSE_INIT_USER_EMAIL` rejects `dev@localhost`; langfuse-web refuses
   to start at all.
6. Prometheus staleness (5 min) meant the cost-per-session panel silently
   forgot every older session until it was rewritten with
   `max_over_time(...[$__range])`.

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
  - Step 12: MODEL_PROFILE validation - VERIFIED. Tested with an invalid
    profile (raises RuntimeError with clear message) and a valid profile
    (passes without error). Also fixed a stale comment in hello_world.py
    that referenced the wrong env var name.
  - Step 20: setup_otel_instrumentation() idempotency - VERIFIED. Called
    twice, confirmed same provider object returned and zero warnings.
    Also found and fixed a related issue: run_otel_to_grafana_demo.py was
    calling LangChainInstrumentor().instrument() a second time redundantly
    (setup_otel_instrumentation() already does this internally) - removed
    the duplicate call.
  - Step 21: OTEL_EXPORTER_OTLP_ENDPOINT load-order bug - VERIFIED AND FIXED.
    Checked all 6 files reading this env var or OTLPSpanExporter. Found 2 with
    the bug (module-level os.getenv() before any load_dotenv() call):
    context_propagation_demo.py and run_openllmetry_demo.py. Added load_dotenv()
    before the getenv() call in both. Verified with a real .env value - both
    files now correctly pick up a custom OTEL_EXPORTER_OTLP_ENDPOINT.
    Other 4 files checked and confirmed safe: otel_setup.py (getenv is inside
    a function, not module-level), send_test_span.py and run_phoenix_demo.py
    (hardcoded endpoints, no env var read), run_otel_to_langfuse_demo.py
    (load_dotenv() already correctly placed before the read).
  - Step 30: two FastAPI response bugs - FIXED AND VERIFIED.
    Bug A (text blocks -> 500): message.content could be a list of blocks
    instead of a plain string, which failed Pydantic validation on
    ResearchResponse.answer. Added _extract_text_content() helper to
    normalize both shapes. Verified: unit test on both input shapes passes,
    and a real HTTP request returns a clean string answer (HTTP 200).
    Bug B (pending interrupt reported as completed): approve() did not
    re-check state.next after resuming, so a second pending interrupt was
    incorrectly reported as status=completed. Added a state.next re-check
    after the resume invoke, mirroring the pattern already used in
    research(). Verified structurally (re-check happens after invoke,
    before the completed response) - a live two-interrupt scenario was not
    reproduced end-to-end since it depends on unpredictable agent behavior,
    noted here rather than silently claimed as fully live-tested.
- Step 18 — DONE. All 10/10 prompts completed (see docs/step18_findings.md).
  rc-008 and rc-009 required a real code fix (unbounded LLM/search timeouts)
  before they would complete at all - documented as Finding 1/2. Finding 3
  covers the lead agent's uncapped self-correction retry loop, now capped.
- Steps 15, 16 — DONE (Langfuse delegation trace + session grouping verified).
- Step 26 — DONE. See docs/step26_langfuse_otel_comparison.md. Found a real
  gap: our IdentitySpanProcessor sets a generic session_id attribute that
  works for Grafana Tempo but is silently ignored by Langfuse'''s OTLP
  ingestion (which needs session.id/user.id or langfuse.session.id/
  langfuse.user.id specifically). Flagged as follow-up, not fixed (affects
  only the direct-OTel-to-Langfuse comparison script, not the main app path).
- Step 22 — DONE. Real comparison saved: docs/step22_openllmetry_vs_openinference.md
  (297 vs 559 spans on identical research task, naming/attribute differences documented)
- Step 19 — DONE. See docs/step19_langgraph_studio_replay.md. Fresh
  replay from the model checkpoint via Studio Fork action, thread
  01a0bad5-0dcb-7143-a121-f4505e4d2791. Also removed .langgraph_api/
  runtime files from git tracking (a related cleanup item from the same
  action plan step that had also been missed).
- Step 32 — DONE. See docs/step32_grafana_session_search.md - fresh session
  search confirmed both via Tempo API (20 traces) and visually in Grafana UI.
- Step 25 — DONE. See docs/step25_context_propagation.md. Repeated with
  real researcher subagent (stub model, no API calls), verified real trace
  IDs differ when broken and match when fixed. Also corrected a false
  claim that asyncio.create_task needed manual context-copying like
  threading.Thread does (it never did - automatic since Python 3.7).
- Step 28 — DONE. See docs/step28_same_run_comparison.md. Same trace ID
  (3afbd592...) confirmed in both Phoenix and Langfuse from one single
  invocation. Found a real gap: Phoenix shows full model-span token
  usage/cost, Langfuse (direct OTel path) shows None for the same span -
  flagged as follow-up, not fixed.
- Documentation corrections (Step 2, Step 5 doc, README Phase 4 claim) — DONE
- Step 9 — DONE. See docs/step9_postgres_deferral_decision.md. Deferral
  to Phase 7 explicitly documented and justified (Phase 7/Step 46 in the
  original brief already places Postgres checkpointing there) - decision
  is now written down instead of only implicit.

## Blockers / open decisions
- Commit fbcdf08 (already on develop before this review cycle) claims to address
  MODEL_PROFILE validation and idempotent otel setup, among other things.
  These specific claims (Step 12, Step 20) still need fresh independent
  verification before being trusted or marked done - this is next up.
- FastAPI root-span identity gap (see Steps 5/24 above) — RESOLVED in
  Phase 5. Fixed in the handler rather than in middleware; the remaining
  ASGI send/receive sub-spans are documented as an accepted limitation.
