# Step 44 — Tail sampling: verification

Config: `collector/otel-collector-config.yaml` (`traces/in` → `forward/sampling`
→ `traces/sampled` with `tail_sampling`). Session flag:
`observability/identity.py::session_sampled`. Plan: `docs/phase7_plan.md` §44,
Q5, Q6.

Policies (OR'd):

| Policy | Keeps |
|---|---|
| `errors` | any span with status ERROR |
| `expensive-model-call` | any span with `gen_ai.usage.cost_usd > 0.01` |
| `session-sampled` | `trace.session_sampled == true`, stamped by the app: sha256(session_id) < `TRACE_SESSION_SAMPLE_RATE` (default 0.2) |

`decision_wait: 300s`, decision cache 100k/100k, `memory_limiter` 80%/20%.

## Run (2026-09-23, collector 0.159.0, grafana/otel-lgtm 0.11.15)

Scripts: `scripts/phase7/step44_send.py` (traffic + manifest) and
`scripts/phase7/step44_check.py` (Tempo lookup, run more than 5 min later).

- Normal traffic: 50 × `POST /research/{uuid}/approve` on the real app. Each
  thread is unknown, so each returns 400 without calling the model. These are
  real app traces with `session_id` and `trace.session_sampled`, and status UNSET.
- Error: `POST /research` on a second app instance started with
  `DEEPSEEK_API_KEY=sk-invalid-step44` → DeepSeek 401 → HTTP 500. The session
  was picked so that the session policy would **drop** it.
- Expensive: one fake `ChatDeepSeek` span sent straight to the collector with
  `gen_ai.usage.cost_usd = 0.02`, plus a control span at `0.005`. Both are on
  sessions the session policy would drop.

Traffic ended at 10:28:41. The collector's `debug` exporter printed the
sampled traces at 10:33:39, 300 s later (= `decision_wait`).

## Results

```
(3) normal: 8/50 in Tempo; predicted 8; mismatches 0
(1) error session (session policy says drop): 1 trace(s) in Tempo
    trace e71c50d95e9a32ea04c07f9410d6be5 root='POST /research' error spans=[('POST /research', 'STATUS_CODE_ERROR'), ('LangGraph', 'STATUS_CODE_ERROR'), ('PatchToolCallsMiddleware.before_agent', 'STATUS_CODE_OK'), ('model', 'STATUS_CODE_ERROR'), ('ChatDeepSeek', 'STATUS_CODE_ERROR')]
(2) fake expensive cost_usd=0.02: 1 trace(s) in Tempo ['5131ad399d2a8a2d0654d7673b2a2ad']
(2) fake cheap_control cost_usd=0.005: 0 trace(s) in Tempo []
```

Metrics check (4), Prometheus, the current collector instance, before the run: no
series. After:

```
sum by (collector_instance_id) (traces_span_metrics_calls_total{span_name="POST /research/{thread_id}/approve",span_kind="SPAN_KIND_SERVER"})
→ {"collector_instance_id":"91ad2f6e-…"} 50
```

| Check | Result |
|---|---|
| 1. Errored trace kept though its session is not sampled | PASS, whole trace kept, root span ERROR |
| 2. Expensive call (> $0.01) kept, cheap control dropped | PASS (0.02 kept, 0.005 dropped) |
| 3. Normal traffic kept at the session rate | 8/50 kept (16%). Exactly the 8 sessions the hash predicted, 0 mismatches. 16% vs the 20% target is sampling variance at N=50 |
| 4. span_metrics count = N | PASS, 50 = 50. Metrics are computed before sampling |

## Findings

- **F44-1 (real): the traces pipeline had to be split.** With `tail_sampling`
  in the single `traces` pipeline, `span_metrics` would have seen only the
  biased sample. All errors are kept but only 20% of successes, so the tool
  error rate would read up to about 5x too high. Check 4 shows the split works.
- **F44-2 (real): per-trace sampling breaks runs.** One run is at least 2
  traces (`/research`, then `/approve`), so independent 20% sampling keeps a
  whole run about 4% of the time. The decision is made per session in the app
  instead (Q6b).
- **F44-3 (real, known trade-off): runs longer than `decision_wait`.**
  A run can take up to about 29 min (Step 42: 1745 s). With the plan's 5 min wait, an
  error or expensive call **after** minute 5 of a trace can't change a decision
  already made. Later spans follow the cached decision. The session policy is
  unaffected. Traces also only become visible in Tempo about 5 min after they end.
- **F44-4 (tooling): a Tempo search quirk.** `/api/search` returned no traces for
  a narrow window around the traffic, or for a window whose `end` was in the
  future. With `[now-1h, now]` it found them. The first check run (10:36)
  reported 0/50 because of this, not because of sampling.
- **F44-5 (gap): the collector's own `otelcol_processor_tail_sampling_*`
  metrics are not in Prometheus.** The collector's internal telemetry isn't
  exported anywhere. The supporting evidence used instead is the `debug`
  exporter output and the Tempo results above.
- A 4xx leaves the server span's status UNSET (the HTTP server semconv rule), so 400s are sampled like normal
  traffic, as the 50 normal runs show.
