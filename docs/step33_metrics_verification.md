# Step 33 — do the GenAI metrics actually exist?

`obs-mon.md` step 33 says:

> The instrumentation already emits `gen_ai.client.token.usage` and
> `gen_ai.client.operation.duration`. Verify they land in Prometheus.

## Verdict: the premise was false for this stack

**They were not emitted by anything.** `openinference-instrumentation-langchain`
emits traces only — its `_instrument()` takes a `tracer_provider` and has no
`meter_provider` parameter at all. Nothing else in the pipeline produced
either metric. The step as written would have been "verified" by looking at
an empty Prometheus and assuming the query was wrong.

So they are produced deliberately, in
`src/research_copilot/observability/metrics_setup.py`, by
`GenAIMetricsCallbackHandler` — a LangChain callback handler, which is the
same extension point Langfuse's own handler uses, so it does not conflict
with the existing tracing.

Both are Histograms, matching the OTel GenAI semantic conventions:

| Metric | Instrument | Unit |
|---|---|---|
| `gen_ai.client.token.usage` | Histogram | `{token}` |
| `gen_ai.client.operation.duration` | Histogram | `s` |

## Verification

Stack up (`docker compose up -d`), API running, then a real
`POST /research` with `user_id=alice`, thread
`da51e2f5-2b1f-4831-9395-f8d1fa1dbfc8`.

Query — Prometheus metric-name listing, through the Grafana datasource
proxy:

```
GET http://localhost:3001/api/datasources/proxy/uid/prometheus/api/v1/label/__name__/values
```

Response, filtered to the relevant names:

```
gen_ai_client_operation_duration_seconds_bucket
gen_ai_client_operation_duration_seconds_count
gen_ai_client_operation_duration_seconds_sum
gen_ai_client_token_usage_bucket
gen_ai_client_token_usage_count
gen_ai_client_token_usage_sum
research_copilot_checkpoint_db_size_bytes
research_copilot_run_steps_bucket
research_copilot_run_steps_count
research_copilot_run_steps_sum
research_copilot_runs_pending_approval
traces_span_metrics_calls_total
traces_span_metrics_duration_milliseconds_bucket
traces_span_metrics_duration_milliseconds_count
traces_span_metrics_duration_milliseconds_sum
```

Label set on one series:

```
GET .../api/v1/series?match[]=gen_ai_client_token_usage_sum

{"__name__":"gen_ai_client_token_usage_sum",
 "gen_ai_operation_name":"chat",
 "gen_ai_provider_name":"deepseek",
 "gen_ai_request_model":"deepseek-chat",
 "gen_ai_token_type":"input",
 "job":"research-copilot-agent",
 "service_name":"research-copilot-agent",
 "session_id":"da51e2f5-2b1f-4831-9395-f8d1fa1dbfc8"}
```

Answer: **yes, they land in Prometheus** — but only because they are now
produced on purpose.

## Two things this verification caught

### 1. `gen_ai_request_model` disagreed with the span

The label above reads `deepseek-chat` (the configured name) while the
corresponding model span carries `gen_ai.request.model = "deepseek-flash"`
(the provider's own alias). The Collector's cost transform keys on the span
value, so a panel joining cost to tokens by model would have matched
nothing and shown an empty graph with no error.

Fixed: `_resolve_model_name()` now prefers the name the provider reported,
falling back to configuration only when the response carries none.

### 2. OTel unit `"1"` becomes a `_ratio` suffix in Prometheus

`research_copilot.runs.pending_approval` was first declared with unit `"1"`
and arrived as `research_copilot_runs_pending_approval_ratio` — the
OTLP-to-Prometheus translation reads unit `1` as a ratio. A count of runs is
not a ratio, and any dashboard written against the obvious name would have
found nothing.

Fixed by using annotation units (`{run}`, `{step}`), which the translation
leaves off the metric name. Re-verified: the series is now
`research_copilot_runs_pending_approval`.

Both of these are the kind of thing that is invisible until someone actually
queries the backend, which is the entire point of the step.

## Where the metrics come from

| Metric | Produced by | Path |
|---|---|---|
| `gen_ai.client.token.usage` | `GenAIMetricsCallbackHandler` (app) | HTTP + CLI |
| `gen_ai.client.operation.duration` | `GenAIMetricsCallbackHandler` (app) | HTTP + CLI |
| `research_copilot.run.steps` | `record_run_steps()` (app) | HTTP + CLI |
| `research_copilot.checkpoint.db_size_bytes` | observable gauge (app) | HTTP + CLI |
| `research_copilot.runs.pending_approval` | observable gauge (app) | HTTP only |
| `traces_span_metrics_*` | `span_metrics` connector (Collector) | everything exporting through the Collector |
