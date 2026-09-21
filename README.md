# Research Copilot — Observability Stack

A "Research Copilot": given a topic, a planner agent breaks the job into
steps, a researcher subagent searches the web and saves notes to files,
and a writer subagent turns those notes into a report. The entire system
is wrapped in observability — every step visible, mistakes catchable,
cost tracked, and improvement provable over time.

## Status

**For the authoritative, step-by-step status, see `docs/progress.md`** —
this table is a rough phase-level summary only. An earlier version of this
table marked every phase through Phase 4 as flatly "Done" while several
individual steps within those phases were still open or only partially
verified; this table now reflects that some phases are mixed rather than
fully complete.

| Phase | What it adds | Status |
|---|---|---|
| 0 | Folder structure, OTel Collector, trace docs | Done |
| 1 | Multi-agent core, checkpointer, human-in-the-loop, streaming, dual model profiles, eval dataset | Mostly done — Postgres checkpointing (Step 9) deferred, see docs/progress.md |
| 2 | Langfuse tracing | Mostly done — Step 19 replay done; Langfuse is now auto-provisioned on first start (see Setup) |
| 3 | OpenTelemetry migration (OpenInference/OpenLLMetry, manual spans, context propagation) | Mostly done — Steps 25 and 26 done; Langfuse double-export closed in Phase 5 |
| 4 | Arize Phoenix, FastAPI endpoint, Grafana/Tempo/Prometheus/Loki | Done — Steps 28 and 32 done; the Collector now carries traces, metrics and logs |
| 5 | Metrics dashboards + alerts | Done — start with [the Phase 5 guide](docs/phase5_evidence/README.md) |
| 6 | Evaluation framework | Not started |
| 7 | Production hardening | Not started |
| 8 | CI/CD | Not started |

## Setup

For the full setup, API approval workflow, observability checks, and a verification checklist for every step in `obs-mon.md` and `review.md`, follow [get-started.md](get-started.md).

```bash
cp .env.example .env     # fill in DEEPSEEK_API_KEY / GROQ_API_KEY
uv sync
docker compose up -d     # 9 containers: Collector, LGTM, Phoenix, Langfuse + its 4 deps
```

Langfuse provisions its own organization, project, user and API keys on
first start from the `LANGFUSE_INIT_*` values in `.env`, and `.env` uses
those same keys — so a fresh clone works without anyone creating a project
by hand. (Before this, a fresh clone got `401 Unauthorized` on every span
export and nothing in the repo said why.)

### Tracing backend switch

`TRACING_BACKEND` decides which pipeline records tool calls:

| Value | Effect |
|---|---|
| `otel` (default) | OpenInference/OTel only. Langfuse's `@observe` is a no-op. |
| `langfuse` | Langfuse decorators active — for the Phase 2 demos. |
| `both` | Both. Accepts 2x tool spans; only for the Step 26/28 comparisons. |

This exists because Langfuse v4 attaches its own span processor to the
global TracerProvider, so an ungated `@observe` exported every tool call
twice — 74 `web_search` spans for 37 real HTTP calls — which made every
Phase 5 tool panel and the tool-error alert exactly 2x wrong.

## Running things

### Dashboards and alerts

```bash
docker compose up -d
# Grafana        http://localhost:3001   (dashboard: "Research Copilot — Phase 5")
# Langfuse       http://localhost:3000
# Phoenix        http://localhost:6006
```

The dashboard (`grafana/dashboards/`) and the five alert rules
(`grafana/provisioning/alerting/`) are provisioned from git, not clicked in,
and LGTM now has persistent volumes — both survive `docker compose down`.

```bash
# Plain agent
uv run python -m research_copilot.agents.main_agent

# Checkpointed agent with human-in-the-loop
uv run python -m research_copilot.agents.checkpointed_agent "your task"

# FastAPI
uv run uvicorn research_copilot.api.main:app --reload

# Grafana dashboard (start containers first)
docker compose up -d otel-collector grafana-lgtm
uv run python -m research_copilot.agents.run_otel_to_grafana_demo
```

## Branching

One branch per phase, cut from `develop`, merged back after review. `main`
updates at milestones (after Phase 1, 4, 8).
