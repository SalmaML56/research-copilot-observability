# Step 48 — Human-in-the-loop approval queue metrics: verification

Plan: `docs/phase7_plan.md` §48, Q10a/Q10b, Q12b.

## What was built

- **`POST /research/{thread_id}/reject`**, with an optional `{"reason": "..."}`
  (Q10a). It resumes with `{"type": "reject", "message": reason}`. With a
  reason, langchain's HITL middleware tells the model why, and the model may
  try again. Without one, the model is told not to retry. `/approve` and
  `/reject` share one resume path (`_resume` in `api/main.py`).
- **`approval_requests` table** in `checkpoint-postgres` (Q10b,
  `observability/approval_queue.py`). There is **one row per pause**:
  `paused_at` (DB `now()`), then `decided_at`, `decision`, `reason`. A partial
  unique index allows at most one open pause per thread. Created at API
  startup, next to the checkpointer's `setup()`.
- **Metrics** (`observability/metrics_setup.py`):
  - `research_copilot.approval.wait_seconds{decision}`: a histogram with
    human-scale buckets (5 s … 1 day). The value is `decided_at - paused_at`, both
    taken from the database clock.
  - `research_copilot.approval.decisions{decision}`: a counter. The rejection rate
    is `reject / all`, **per decision** (one run can produce several).
  - `research_copilot.runs.pending_approval` now counts open rows in
    `approval_requests` (Q12b). It used to be an in-process `set`, which reset to 0 on
    restart. It reports 0 if the table doesn't exist yet (CLI processes).
- The decision is recorded when it **arrives**, before the resumed run's
  model calls. The resumed run's duration is not approval wait.
- **Dashboard:** a new "Approval queue" row with p50/p95 wait and the rejection
  rate (per decision) panels. Grafana reloaded them (checked via the API).

## Verification run (2026-09-23, real DeepSeek runs)

Script: `scripts/phase7/step48_approval.py`. Topic: "Research the current
status of the ITER fusion project and write a short report."

1. `pause`: 3 real `/research` runs (A, B, C) until `paused_for_approval`.
2. The app was **restarted** between pause and decision (killed 11:22:31, up 11:22:42).
   - Pending gauge before: `3` (instance `cb1d672a`). After the restart: `3` from
     the **new** instance `6a2db69d`. The old in-process set would have read 0.
3. `decide`: A approve; B reject **with** a reason; C reject **without**
   one. Any re-pause is approved after 15 s.

Client log vs the `approval_requests` rows:
```
  A round 1: approve reason=False expected_wait~   56.2s -> http 200 completed
  B round 1: reject  reason=True  expected_wait~  979.7s -> http 200 paused_for_approval
  B round 2: approve reason=False expected_wait~   15.0s -> http 200 completed
  C round 1: reject  reason=False expected_wait~  491.2s -> http 200 completed

 run | id | decision | has_reason | wait_s
-----+----+----------+------------+--------
 B   |  1 | reject   | t          |  979.9
 C   |  2 | reject   | f          |  491.3
 A   |  3 | approve  | f          |   58.0
 B   |  4 | approve  | f          |   15.1
```
The reject semantics behaved as specified. B (reason given) retried
`finalize_report` and paused again. C (no reason) did not retry and completed.
The expected wait is measured from when the client *saw* the pause response.
The DB measures from the pause itself, which is up to 1.8 s earlier (A).

Prometheus (same instance `6a2db69d`, after the restart):
```
research_copilot_approval_decisions_total{decision="approve"}  2
research_copilot_approval_decisions_total{decision="reject"}   2
research_copilot_approval_wait_seconds_sum{decision="approve"} 73.088951    (58.0 + 15.1)
research_copilot_approval_wait_seconds_sum{decision="reject"}  1471.204187  (979.9 + 491.3)
sum(decisions{reject}) / sum(decisions)                        0.5
research_copilot_runs_pending_approval{instance 6a2db69d}      0
```
Postgres: `SELECT avg((decision='reject')::int) FROM approval_requests WHERE decided_at IS NOT NULL` → `0.5`.
The dashboard's p95 query returned 576.8 s. That's a bucket-interpolated
estimate (the 979.9 s wait sits in the 600–1800 s bucket), not an exact value.

## Findings

- **F48-1 (real): the approval gate can be skipped by the model.** On the first
  attempt with the short topic "In two sentences, what is a tokamak?", **2 of 3
  runs returned `completed` without ever calling `finalize_report`**, so
  there was no pause and no approval. The gate is enforced only by
  `LEAD_AGENT_SYSTEM_PROMPT`, not by the graph. The old comment in
  `api/main.py` ("research() essentially never returns completed directly")
  held for research-style topics only. This isn't fixed here: making
  approval mandatory is a product decision (e.g. force `finalize_report` via
  the graph). The queue metrics count decisions on pauses that do happen. They say
  nothing about runs that skipped the gate.
- **F48-2 (real): a stale gauge series after a restart.** The killed process's last
  `pending_approval` value (`3`, instance `cb1d672a`) stays in Prometheus
  for its lookback window (~5 min, OTLP push has no staleness marker). The panel and alert use
  `max()`, so they can show the old value for up to ~5 min after a restart. The
  alert needs 10 min above threshold, so it isn't affected. Every instance now reports the
  same DB-wide count, so `max()` (not `sum()`) stays the right aggregation
  with several replicas.
- **F48-3 (gap): pauses from before this table existed** have no row. If one
  is decided, the decision is counted but no wait is recorded (warning
  logged), and it doesn't show in the pending gauge. Nothing was backfilled.
- **F48-4 (gap):** `reason` is stored in Postgres as free text, outside
  the collector's redaction (listed in `docs/step45_redaction.md`).
- **F48-5 (known Prometheus behaviour):** `increase()` over a brand-new
  counter series extrapolates. The rate panel showed 0.502 for an exact 0.5.
  Postgres is the exact source.
