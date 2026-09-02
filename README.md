# Research Copilot — Observability Stack

A "Research Copilot": given a topic, a planner agent breaks the job into
steps, a researcher subagent searches the web and saves notes to files, and
a writer subagent turns those notes into a report. The entire system is
wrapped in observability — every step visible, mistakes catchable, cost
tracked, and improvement provable over time.

Built with Deep Agents (LangGraph-based), served via FastAPI, and
instrumented end-to-end with OpenTelemetry, Langfuse, Phoenix, and Grafana.

## Status

This project is built phase by phase, each on its own branch, merged into
`develop`. See `docs/progress.md` for exactly which phase/step is currently
in progress.

| Phase | What it adds | Status |
|---|---|---|
| 0 | Folder structure, OTel Collector (debug exporter), trace docs | Done |
| 1 | Deep Agent core: planner + researcher + writer subagents | In progress |
| 2 | Langfuse tracing | Not started |
| 3 | Migrate to OpenTelemetry (OpenInference/OpenLLMetry) | Not started |
| 4 | Arize Phoenix + Grafana/Tempo/Prometheus/Loki stack | Not started |
| 5 | Metrics dashboards + alerts | Not started |
| 6 | Evaluation framework (DeepEval/Ragas, trajectory scorers) | Not started |
| 7 | Production hardening (sampling, PII redaction, load test) | Not started |
| 8 | CI/CD (eval-gated PRs, prompt versioning, runbook) | Not started |

## Prerequisites

- Docker (Desktop or Engine + Compose)
- Python 3.11+
- `uv` — this project's package manager (never `pip`/`poetry` directly)
- Git
- An Anthropic API key (this project uses Claude as its model provider)

## Setup

```bash
cp .env.example .env
# edit .env, set grok_API_KEY

uv sync
```

## Running things

Bring up the OTel Collector (Phase 0):

```bash
docker compose up -d
uv run python -m research_copilot.observability.send_test_span
docker compose logs otel-collector | tail -40
```

Run the hello-world agent (Phase 1, step 6):

```bash
uv run python -m research_copilot.agents.hello_world
```

## Project layout

See `docs/trace-contract.md`, `docs/trace-vs-span.md`, `docs/otel-genai-cheatsheet.md`,
and `docs/langchain-layers.md` for the design notes written during Phase 0.

## Branching

One branch per phase, cut from `develop`, merged back into `develop` after
review. `main` only receives a merge from `develop` at stable milestones
(after Phase 1, Phase 4, Phase 8). See `docs/progress.md` for session
handoff notes if a session ends mid-phase.
