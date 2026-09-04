# Research Copilot — Observability Stack

A "Research Copilot": given a topic, a planner agent breaks the job into
steps, a researcher subagent searches the web and saves notes to files, and
a writer subagent turns those notes into a report. The entire system is
wrapped in observability — every step visible, mistakes catchable, cost
tracked, and improvement provable over time.

Built with Deep Agents (LangGraph-based), served via FastAPI, and
instrumented end-to-end with OpenTelemetry, Langfuse, Phoenix, and Grafana.

## Status

| Phase | What it adds | Status |
|---|---|---|
| 0 | Folder structure, OTel Collector (debug exporter), trace docs | Done |
| 1 | Deep Agent core: planner + researcher + writer, checkpointer, human-in-the-loop, streaming, dual model profiles, test dataset | Done |
| 2 | Langfuse tracing | In progress |
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
- A DeepSeek API key (primary model), optionally a Groq API key (cheap/alternate profile)

## Setup

```bash
cp .env.example .env
# edit .env, set DEEPSEEK_API_KEY (and optionally GROQ_API_KEY)

uv sync
```

## Running things

Bring up the OTel Collector (Phase 0):

```bash
docker compose up -d
uv run python -m research_copilot.observability.send_test_span
docker compose logs otel-collector | tail -40
```

Run the plain agent (Phase 1, steps 6-8):

```bash
uv run python -m research_copilot.agents.main_agent
```

Run with a checkpointer + human-in-the-loop approval (Phase 1, steps 9-10):

```bash
uv run python -m research_copilot.agents.checkpointed_agent "your research task"
uv run python -m research_copilot.agents.run_interrupt_demo
```

Run with streaming typed events (Phase 1, step 11):

```bash
uv run python -m research_copilot.agents.run_streaming_demo
```

Switch to the cheap/free model profile (Phase 1, step 12):

```bash
MODEL_PROFILE=cheap uv run python -m research_copilot.agents.main_agent
```

## Project layout

See `docs/trace-contract.md`, `docs/trace-vs-span.md`, `docs/otel-genai-cheatsheet.md`,
and `docs/langchain-layers.md` for the design notes written during Phase 0.

`data/test_dataset.jsonl` holds 25 research prompts with expected facts,
used for Phase 6 evaluation.

## Branching

One branch per phase, cut from `develop`, merged back into `develop` after
review. `main` only receives a merge from `develop` at stable milestones
(after Phase 1, Phase 4, Phase 8). See `docs/progress.md` for session
handoff notes if a session ends mid-phase.
