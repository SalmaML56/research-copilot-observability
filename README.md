# Research Copilot — Observability Stack

A "Research Copilot": given a topic, a planner agent breaks the job into
steps, a researcher subagent searches the web and saves notes to files,
and a writer subagent turns those notes into a report. The entire system
is wrapped in observability — every step visible, mistakes catchable,
cost tracked, and improvement provable over time.

## Status

| Phase | What it adds | Status |
|---|---|---|
| 0 | Folder structure, OTel Collector, trace docs | Done |
| 1 | Multi-agent core, checkpointer, human-in-the-loop, streaming, dual model profiles, eval dataset | Done |
| 2 | Langfuse tracing | Done |
| 3 | OpenTelemetry migration (OpenInference/OpenLLMetry, manual spans, context propagation) | Done |
| 4 | Arize Phoenix, FastAPI endpoint, Grafana/Tempo/Prometheus/Loki | Done |
| 5 | Metrics dashboards + alerts | Not started |
| 6 | Evaluation framework | Not started |
| 7 | Production hardening | Not started |
| 8 | CI/CD | Not started |

## Setup

```bash
cp .env.example .env
uv sync
docker compose up -d otel-collector
```

## Running things

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
