# Step 47 — Load test: 20 concurrent sessions, no cross-session leakage

Plan: `docs/phase7_plan.md` §47, Q8c, Q9a. Script: `scripts/load_test.py`.

## What was built

- `scripts/load_test.py run` fires N concurrent `POST /research`, each with a
  unique `thread_id` (`lt-<i>-<hex>`), `user_id` (`lt-user-<i>`) and a
  marker `LT-<i>-<hex>` in the topic. It then approves every paused run
  concurrently and samples the collector's memory (`docker stats`) every ~2 s.
- `scripts/load_test.py check` runs more than 5 min later (`decision_wait`) and needs no eyeballing. For
  each session:
  - **Tempo:** every trace found by `session_id`. Every span's `session_id`
    must be this session's, `user_id` must be this session's (or
    `unknown`, which `/approve` uses), and no other session's marker may
    appear anywhere in the span. The check also looks for any trace returned by
    two sessions' searches.
  - **Loki:** every log line with this `session_id` is scanned for other sessions' markers.
  - **Postgres checkpoints:** every row of `checkpoints`,
    `checkpoint_blobs` and `checkpoint_writes` for this `thread_id` is scanned
    for other sessions' markers, and its own marker must be present.
  - **`approval_requests`:** exactly one decided row per thread.
- `MODEL_PROFILE=stub` (Q8c, `agents/stub_model.py`): a scripted model
  that runs the **real** graph. That covers lead agent → `task` → researcher
  (`write_file`) → `task` → writer (`read_file`) → `finalize_report` pause →
  approve, over the real FastAPI app, Postgres checkpointer, identity
  ContextVar and OTel pipeline. Only the LLM call is replaced. Each call has
  0.2–1.5 s of random latency so sessions interleave. It echoes the session's marker
  into every message and file, so any cross-session state shows up as a
  foreign marker. The metrics label it `provider=stub`, `model=stub`.
- Q9a: the app was started with `TRACE_SESSION_SAMPLE_RATE=1.0`, so every
  load-test session is kept by the real tail sampler.

## Run 1: 20 concurrent sessions, stub model (2026-09-23 11:27)

```
20 sessions, wall time 15.4s
 i thread_id          /research status                   s | /approve status         s answer-has-own-marker
 0 lt-0-6a030f7a            200 paused_for_approval    7.8 |      200 completed    1.2 True
 …  (all 20 rows: 200 paused_for_approval 6.9–10.9 s | 200 completed 1.2–4.4 s | True)
19 lt-19-17fbe511           200 paused_for_approval    8.8 |      200 completed    3.6 True
completed with own marker in answer: 20/20
collector memory: 5 samples every ~2s; first 64.09MiB / 512MiB; peak 85.68MiB / 512MiB
```
20 runs of 7–11 s each finished in 15.4 s of wall time, so they genuinely ran
concurrently. The collector's memory while it held the spans for `decision_wait`
(11 samples, one every 30 s): peak 82.7 MiB of 512 MiB.

Leakage check (11:33, after `decision_wait`):
```
 i traces  spans no-sid  foreign sid/user/marker |  logs foreign | ckpt rows foreign
 0      2     48      0                        0 |     4       0 |       111       0
 …  (identical for all 20 sessions)
19      2     48      0                        0 |     4       0 |       111       0
traces found in more than one session's search: 0
approval_requests rows: 20 (20 approve) over 20 threads
sessions with 0 traces in Tempo: 0
LEAKAGE PROBLEMS: 0
```
Every session has exactly its 2 traces (`/research`, `/approve`) and 48
spans. Every span carries its own `session_id` (0 without one), and there are 0 foreign
IDs or markers in 960 spans, 80 log lines and 2,220 checkpoint rows.

## Run 2: 5 concurrent sessions, real DeepSeek (2026-09-23 11:34)

Topic: "Research the current status of small modular nuclear reactors and
write a short report. Reference code: {marker}".
```
5 sessions, wall time 232.0s
 0 lt-0-03e68a14            200 paused_for_approval  205.0 |      200 completed    3.8 True
 1 lt-1-cd8128a0            200 paused_for_approval  192.6 |      200 completed    3.6 False
 2 lt-2-3af45778            200 paused_for_approval  193.7 |      200 completed    6.8 True
 3 lt-3-a6df633f            200 paused_for_approval  194.0 |      200 completed    3.9 False
 4 lt-4-57560c50            200 paused_for_approval  225.2 |      200 completed    3.2 True
completed with own marker in answer: 3/5
collector memory: 76 samples every ~2s; first 90.92MiB / 512MiB; peak 93.79MiB / 512MiB
```
All 5 paused and completed. The 3/5 "own marker in answer" isn't leakage: the real
model repeated the reference code in 3 of 5 final answers. The leakage check below
looks for *foreign* markers.

Leakage check (11:43, after `decision_wait`):
```
 i traces  spans no-sid  foreign sid/user/marker |  logs foreign | ckpt rows foreign
 0      2    197      0                        0 |    48       0 |       349       0
 1      2    186      0                        0 |    46       0 |       305       0
 2      2    168      0                        0 |    40       0 |       303       0
 3      2    169      0                        0 |    43       0 |       276       0
 4      2    169      0                        0 |    41       0 |       291       0
traces found in more than one session's search: 0
approval_requests rows: 5 (5 approve) over 5 threads
sessions with 0 traces in Tempo: 0
LEAKAGE PROBLEMS: 0
```
The real runs cover the path the stub skips: concurrent `web_search` calls and
real DeepSeek calls, 889 spans with 0 missing `session_id`.

## Findings

- **No cross-session leakage** in traces, logs, checkpoints or the approval
  table, at 20 concurrent sessions (stub) and 5 concurrent real runs. The
  risk the plan named (identity in a `ContextVar`, sync endpoints on
  threadpool threads, a new `PostgresSaver` per request over one shared pool
  of 10 connections for 20 sessions) did not show up.
- **Collector memory is not a concern at this load.** It peaked at 94 MiB of 512 MiB
  with every span held for 5 min. `memory_limiter` (80%) never came near.
- **Limits of this test:**
  - The stub skips `web_search` and real model latency, so the 20-session run
    tests concurrency in the app/graph/checkpointer/telemetry, not DeepSeek or
    DuckDuckGo rate limits. The 5 real runs cover the real path at lower concurrency.
  - It's one uvicorn process, so there's no cross-process contention.
  - The approval gate skip (F48-1) wasn't hit here: all runs used research-style
    topics and all of them paused.
