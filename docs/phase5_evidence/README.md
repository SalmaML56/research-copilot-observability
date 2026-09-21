# Phase 5 in five minutes

Traces tell you what happened in one run. Phase 5 adds the other half:
**how things are going overall** — and it tells you before a user does.

Four things now exist that didn't before: numbers in Prometheus, a dollar
figure on every model call, one dashboard, five alerts, and logs you can
jump to from a trace.

---

## Try it

```bash
docker compose up -d
uv run uvicorn research_copilot.api.main:app --port 8000
```

```bash
curl -X POST http://localhost:8000/research \
  -H "Content-Type: application/json" \
  -d '{"topic": "what are OpenTelemetry span metrics", "user_id": "alice"}'
```

It pauses for your approval. Approve it with the `thread_id` it gave you:

```bash
curl -X POST http://localhost:8000/research/<thread_id>/approve
```

Then open **http://localhost:3001** → *Research Copilot — Phase 5*.

Everything on that page is live: the dashboard and all five alert rules are
provisioned from files in `grafana/`, so they come back after
`docker compose down`.

---

## What you're looking at

| Panel | The question it answers |
|---|---|
| p95 / p50 latency | Which agent, subagent or tool is slow — and is it the tail or everything? |
| Tokens per session | Who is burning context, input vs output |
| Cost per session | What this run actually cost, in dollars |
| Tool-call error rate | Are the tools working? Red line at 10% |
| Average steps per run | Is the planner planning, or looping? |
| Runs awaiting approval | Is anyone actually clicking approve? |
| Subagent depth | How much work gets delegated, and how deep |
| Checkpoint DB size | Is state growing faster than it should? |

## The five alerts

Each threshold is calibrated against real runs on this stack, and the
reasoning for every one is in the comment above it in
`grafana/provisioning/alerting/research-copilot-alerts.yaml`.

1. A run planned more than **25 steps** — probably a loop.
2. One user's token cost ran **5x** its own trailing-hour rate.
3. Tool failures went over **10%**.
4. More than **5 runs** stuck waiting for a human.
5. Checkpoint DB growing faster than **5 MB/hour**.

---

## Trace ↔ logs, both ways

This is the part worth seeing yourself.

- **From a trace:** open any span in Tempo, click the little logs icon
  ("Explore the logs for this in split view"). Loki opens beside it, already
  filtered to that trace.
- **From a log:** expand any log line in Loki, click `Trace: <id>`. Tempo
  opens on that exact trace.

Every log line is JSON and carries `trace_id`, `span_id`, `session_id`,
`user_id`, `environment` and `prompt_version`. Before Phase 5 the project
had no logging at all — only `print()`.

---

## One setting you should know about

`TRACING_BACKEND` in `.env` decides which pipeline records tool calls:

| Value | What happens |
|---|---|
| `otel` *(default)* | OpenTelemetry only. Use this. |
| `langfuse` | Langfuse decorators on — for the Phase 2 demos. |
| `both` | Both pipelines, and **2x tool spans**. Only for the Step 26/28 comparisons. |

Why it exists: Langfuse v4 quietly attaches its own span processor to the
global tracer, so an ungated `@observe` exported every tool call twice — 74
`web_search` spans for 37 real HTTP calls. Every tool panel and the tool
error alert were exactly 2x wrong until this switch landed.

Langfuse also provisions its own org, project, user and API keys on first
start now, so a fresh clone just works. It used to hand you
`401 Unauthorized` on every span export with nothing in the repo explaining
why.

---

## Where things live

| | |
|---|---|
| Dashboard | `grafana/dashboards/research-copilot.json` |
| Alert rules | `grafana/provisioning/alerting/research-copilot-alerts.yaml` |
| Metrics code | `src/research_copilot/observability/metrics_setup.py` |
| Logging code | `src/research_copilot/observability/logging_setup.py` |
| Cost rules | `collector/otel-collector-config.yaml` (`transform/cost`) |
| Prices + as-of date | `docs/step34_cost_model.md` |

---

## Going deeper

- **[verification-details.md](verification-details.md)** — every claim above
  with the trace ID, the query and the number behind it, plus the mistakes
  found along the way (three of them only showed up when the backend was
  actually queried).
- **`docs/tasks-ph5.md`** — task-by-task status.
- **`docs/step33_metrics_verification.md`** — why the two GenAI metrics had
  to be built by hand.
- **`docs/step35_37_decisions.md`** — how subagent depth is measured, and
  what must never be logged.

The eight screenshots in this folder are the durable record; the trace IDs
in them will eventually age out of Tempo.
