# Phase 5 evidence

Everything here was captured on **2026-09-21** against the full local stack
(`docker compose up -d`, all 9 containers running) with real agent runs
against DeepSeek — not synthetic data, not a mocked model.

## The runs behind this evidence

| Session (thread) | User | Outcome | Root trace |
|---|---|---|---|
| `da51e2f5-2b1f-4831-9395-f8d1fa1dbfc8` | `alice` | paused for approval | `78ffbbd5c40298d8648f2d9bd811a245` (202 spans, 164.8 s) |
| `879d67dd-68f6-47f4-a084-60e1b9041353` | `bob` | paused → **approved → completed** (1641-char answer) | `60235d941d53d301ddf0714cc766163e` (104 spans) + `1c6c0d55e7f96e52c73ab7d17abe0f35` (approve) |

Note: LGTM keeps no data forever, so these trace IDs will eventually age
out even with the new persistent volumes. The screenshots are the durable
record.

## Screenshots

| File | Shows |
|---|---|
| `01-dashboard.png` | The Step 35 dashboard, all 9 panels with real data, 0 panels in error, 0 showing "No data" |
| `02-alerts.png` | All 5 Step 36 rules, every one marked **Provisioned**, with "Run exceeded 25 planning steps" in the **Firing** state |
| `03-loki-log-details.png` | A Loki log line expanded, carrying `trace_id`, `session_id`, `user_id`, `environment`, `prompt_version` |
| `04-loki-to-tempo-jump.png` | Result of clicking the log's `Trace: 60235d…` derived field — Tempo opens on that exact trace |
| `05-tempo-trace.png` | The trace in Tempo: `POST /research → LangGraph → model → ChatDeepSeek → tools → task`, 104 spans |
| `06-tempo-to-loki-jump.png` | Result of clicking "Explore the logs for this in split view" — Tempo and Loki side by side, 19 log lines for that trace |
| `07-phoenix.png` | Phoenix up on :6006 with the tracing project |
| `08-langfuse-provisioned.png` | Langfuse signed in as the **auto-provisioned** local user, organization and project present |

## Numbers verified by query, not by eye

### P5-01 — span attribute limit (review v2, Addendum C)

Trace `78ffbbd5…`, 202 spans:

```
spans with droppedAttributesCount > 0 : 0
spans carrying session_id             : 199 / 202
```

The 3 without are `POST /research http send` (x2) and
`POST /research http receive` — ASGI plumbing spans created outside the
route handler. Before the fix, 10 of 349 `ChatDeepSeek` spans had lost all
four identity attributes, every one of them with dropped attributes.

The root `POST /research` span now carries all four:

```
session_id     = da51e2f5-2b1f-4831-9395-f8d1fa1dbfc8
user_id        = alice
prompt_version = v1
environment    = dev
```

`user_id` is a real value because the API now accepts one. It used to be
hardcoded `"unknown"`, which made the per-user cost alert meaningless.

### P5-02 — Langfuse double-export (review v2, Addendum D)

| | Before | After |
|---|---|---|
| `web_search` spans | 74 | 25 |
| `web_search.ddgs_http_call` spans | 37 | 28 |
| `langfuse.*` attributes in Tempo | 224 | **0** |

One tool span per tool call. Every tool count, error rate and latency
panel was 2x wrong before this.

### Span status (prerequisite for alert c)

```
web_search.ddgs_http_call  STATUS_CODE_OK    : 23
web_search.ddgs_http_call  STATUS_CODE_ERROR :  5
whole trace                UNSET             :  4
```

Before: 0 ERROR, 78 UNSET — a failure-rate alert would have read 0%
forever. The real rate here is 5/28 = 17.9%.

### P5-24 — cost arithmetic

One `ChatDeepSeek` span from the live trace:

```
gen_ai.request.model       = deepseek-flash
gen_ai.usage.input_tokens  = 6159
gen_ai.usage.output_tokens = 563
gen_ai.usage.cost_usd      = 0.00228223
```

By hand: `6159 x 0.00000027 + 563 x 0.0000011 = 0.00228223`. Exact.

Per-span only, never aggregated onto parents:

```
spans with gen_ai.usage.cost_usd    : 26
spans with gen_ai.usage.input_tokens: 26
ChatDeepSeek model spans            : 26
```

### P5-04 — persistence

Tested three ways, each stronger than the last.

1. `docker compose restart grafana-lgtm`
2. `docker compose rm -sf grafana-lgtm && docker compose up -d grafana-lgtm`
   — container destroyed and rebuilt
3. **`docker compose down && docker compose up -d`** — the whole stack torn
   down, network removed, every container recreated

After (3):

```
Prometheus sessions retained : 2
Tempo trace 60235d… retained : 104 spans
Dashboard retained           : Research Copilot — Phase 5
Alert rules retained         : 5
Langfuse auth after down/up  : {"data":[{"id":"research-copilot-dev",...}]}
```

Before this, `grafana-lgtm` had no volume at all: every dashboard, alert
rule and stored trace was lost on restart.

### P5-46 — alerts actually fired

Two of the five were observed `Firing` on real data, at different times:

```
firing  | A user's token cost spiked 5x within an hour      (after the two research runs)
firing  | Run exceeded 25 planning steps (probable loop)    (after a recorded 31-step run)
```

Neither needed a lowered threshold or a synthetic trigger.

A third, **tool failure rate above 10%**, is `Normal` now only because no
tool calls are in flight. Its expression genuinely crossed the line during
the runs — queried over the run window:

```
tool=web_search  max_error_rate = 0.1538  (36 sample points)
```

15.38% against a 10% threshold. The rule is correct and the data really
did breach it.

### The run-steps alert took three attempts — worth recording

This is the clearest example of why "the query looks right" is not
verification.

1. `max(bucket{le="+Inf"}) - max(bucket{le="25"})`
   **Wrong.** `max()` picks the largest value of *each bucket
   independently across instances*. An over-budget run in the CLI process
   was masked by a larger, entirely within-budget count in the API
   process. The rule read **0** while a 31-step run sat plainly in the
   data.

2. `increase(bucket{le="+Inf"}[30m]) - ignoring(le) increase(bucket{le="25"}[30m])`
   **Also wrong.** A process that records its over-budget run *before* its
   first export has a flat counter for its entire life, and `increase()`
   of a flat series is 0. Measured: the series read `le=+Inf 1` /
   `le=25 0` — the run was right there — while `increase()` returned 0 for
   both buckets.

3. `max(bucket{le="+Inf"} - ignoring(le) bucket{le="25"})`
   **Correct**, and it fires. The trade-off is stated in the rule's own
   comment and description: it latches for the lifetime of the process
   that recorded the run. For "a run probably looped, go and look", that
   is the honest behaviour, and it is not a rate.

### P5-03 — Langfuse is reproducible now

```
GET /api/public/health                 -> {"status":"OK","version":"4.37.0"}
GET /api/public/projects (Basic auth)  -> {"data":[{"id":"research-copilot-dev",
                                           "name":"research-copilot",
                                           "organization":{"id":"research-copilot-local"}}]}
```

The keys in `.env` are the keys `LANGFUSE_INIT_*` creates, so they cannot
drift apart. Signing into the UI with the provisioned user works
(`08-langfuse-provisioned.png`).

One gotcha found and fixed while doing this: `LANGFUSE_INIT_USER_EMAIL`
is validated, and `dev@localhost` is rejected — langfuse-web refused to
start with `❌ Invalid environment variables:
{ LANGFUSE_INIT_USER_EMAIL: [ 'Invalid input' ] }`. It needs a
dotted domain; `dev@research-copilot.local` is accepted.

The Langfuse project will be **empty** under the default
`TRACING_BACKEND=otel`, and that is correct — the whole point of P5-02 is
that the OTel path no longer also feeds Langfuse. Set
`TRACING_BACKEND=langfuse` (or `both`) to send traces there.
