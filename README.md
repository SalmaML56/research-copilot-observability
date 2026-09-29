# Research Copilot — Observability Stack

A multi-agent research assistant, built as a vehicle for learning and
comparing LLM observability tooling end to end.

Given a topic, a **lead agent** plans the work, a **researcher** subagent
searches the web and writes notes to a shared virtual filesystem, and a
**writer** subagent turns those notes into a report. A human approves the
report before it is finalized. Every step is traced, costed, measured,
evaluated and gated in CI.

Built on LangGraph / Deep Agents, OpenTelemetry, Langfuse (self-hosted),
Arize Phoenix, and the Grafana LGTM stack (Tempo, Prometheus, Loki).

## Architecture

```
FastAPI (/research, /research/stream, /approve, /reject)
   │
   ▼
Lead agent ──► researcher subagent ──► web search, write_file
   │       └─► writer subagent     ──► report
   │  human-in-the-loop pause before finalize_report
   │  checkpoints: Postgres (checkpoint-postgres)
   ▼
OpenInference / OTel SDK ──► OTel Collector
                               ├─ redaction (emails, phones, keys)
                               ├─ span metrics (100% of spans)
                               └─ tail sampling ──► Tempo
                             ──► Prometheus, Loki (Grafana)
                             ──► Phoenix, Langfuse
```

Model profiles: `primary` (DeepSeek), `cheap` (Groq open-weight), `stub`
(scripted model, no API calls — used for load tests and the CI smoke job).

## Project status

`docs/progress.md` is the authoritative, step-by-step record. This table is
a phase-level summary; "Mostly done" means the phase's steps were built and
verified, with specific gaps documented rather than hidden.

| Phase | What it adds | Status |
|---|---|---|
| 0 | Folder structure, OTel Collector, trace contract and reference docs | Done |
| 1 | Multi-agent core, checkpointer, human-in-the-loop, streaming, dual model profiles, eval dataset | Done — Postgres checkpointing (Step 9) was deferred, then implemented in Phase 7 (Step 46) |
| 2 | Langfuse tracing | Mostly done — Step 19 replay done; Langfuse is auto-provisioned on first start |
| 3 | OpenTelemetry migration (OpenInference/OpenLLMetry, manual spans, context propagation) | Mostly done — Steps 25 and 26 done; Langfuse double-export closed in Phase 5. Langfuse's OTLP ingestion ignores the generic `session_id` attribute (Step 26, affects only the direct-OTel-to-Langfuse comparison path) |
| 4 | Arize Phoenix, FastAPI endpoint, Grafana/Tempo/Prometheus/Loki | Done — Steps 28 and 32 done; the Collector carries traces, metrics and logs |
| 5 | Metrics dashboards and alerts | Done — see the [Phase 5 guide](docs/phase5_evidence/README.md) |
| 6 | Evaluation framework (offline, online, failure-to-dataset loop, A/B, human feedback) | Mostly done — Steps 38–43 built and verified live, but offline evals cover 5 of 25 dataset prompts (by scope decision), and the Step 42 A/B cheap arm completed 0/5 (Groq rate limits), so there is no cost/quality comparison |
| 7 | Production hardening | Mostly done — Steps 44–48 done (Postgres checkpoints, tail sampling, redaction, approval metrics, load test); LangGraph Server skipped (needs a LangSmith key), and redaction doesn't cover the app's stdout log, checkpoint DB or eval files |
| 8 | CI/CD | Mostly done — Steps 49–51 done (PR eval gate at threshold 0.6, prompt versioning, bad-trace runbook); the gate runs only rc-001..003, and `eval-gate`/`smoke` are not yet required checks (needs repo owner) |

## Getting started

### Prerequisites

- Python 3.11 and [uv](https://docs.astral.sh/uv/)
- Docker with Compose
- API keys: DeepSeek (primary model) and Groq (cheap model and eval judge)

### Setup

```bash
cp .env.example .env     # fill in DEEPSEEK_API_KEY and GROQ_API_KEY
uv sync
docker compose up -d     # 10 containers: Collector, LGTM, Phoenix,
                         # checkpoint Postgres, Langfuse + its 4 dependencies
```

Langfuse provisions its own organization, project, user and API keys on
first start from the `LANGFUSE_INIT_*` values in `.env`, and the app uses
those same keys, so a fresh clone needs no manual Langfuse setup.

| UI | URL |
|---|---|
| Grafana (dashboard "Research Copilot — Phase 5", 5 alert rules) | http://localhost:3001 |
| Langfuse | http://localhost:3000 |
| Phoenix | http://localhost:6006 |

The Grafana dashboard and alert rules are provisioned from `grafana/`, not
configured by hand, and survive `docker compose down`.

### Running

```bash
# API (research, streaming, approve/reject)
uv run uvicorn research_copilot.api.main:app --reload

# Checkpointed agent with human-in-the-loop, from the command line
uv run python -m research_copilot.agents.checkpointed_agent "your task"

# Plain agent
uv run python -m research_copilot.agents.main_agent

# Unit tests
uv run pytest tests
```

Set `MODEL_PROFILE=stub` to run the full graph without any model API calls.

### Tracing backend switch

`TRACING_BACKEND` selects which pipeline records tool calls:

| Value | Effect |
|---|---|
| `otel` (default) | OpenInference/OTel only; Langfuse's `@observe` is a no-op |
| `langfuse` | Langfuse decorators active (Phase 2 demos) |
| `both` | Both — produces 2x tool spans; only for the Step 26/28 comparisons |

The gate exists because Langfuse v4 attaches its own span processor to the
global TracerProvider: ungated, every tool call was exported twice, which
made every tool panel and the tool-error alert exactly 2x wrong.

## Key findings and decisions

Each step has a write-up in `docs/` with real commands and output. The most
consequential:

- **Observability backends compared on the same run.** One invocation, one
  trace ID, viewed in both Langfuse and Phoenix: Langfuse reads best as a
  single trace's story and shows cost on the sessions list; Phoenix is
  better for searching across many traces, and was the only one of the two
  showing token usage/cost on model spans via the direct OTel path.
  OpenLLMetry vs OpenInference on an identical task: 297 vs 559 spans.
  ([langfuse-vs-phoenix](docs/langfuse-vs-phoenix.md),
  [step 28](docs/step28_same_run_comparison.md),
  [step 22](docs/step22_openllmetry_vs_openinference.md))
- **SQLite → Postgres checkpoints.** Deferred from Phase 1 with a written
  rationale, then implemented in Phase 7 as a dedicated `checkpoint-postgres`
  service with a shared psycopg pool; verified by pausing a run, `kill -9`,
  and resuming it from a fresh process. The same work found that ASGI
  instrumentation made one span per SSE chunk (1,085 of 1,270 spans in one
  run), which is now excluded.
  ([step 9](docs/step9_postgres_deferral_decision.md),
  [Phase 7 in progress.md](docs/progress.md))
- **Tail sampling without skewing metrics.** Span metrics are computed on
  100% of spans before sampling; Tempo keeps every error, every model call
  over $0.01 and ~20% of sessions, decided per session.
  ([step 44](docs/step44_tail_sampling.md))
- **CI eval gate.** Every PR runs a $0 stub-model smoke job, then three
  dataset prompts on DeepSeek, judged for correctness by a Groq model, with
  a pass/fail/inconclusive verdict at threshold 0.6. Building it exposed a
  judge false positive (reports that gave up still named the expected
  keywords) and the root cause of the earlier handoff failures: the
  researcher's notes hit the 4,096-token output cap and the truncated tool
  call was silently dropped. After the fix, CI went from 0/3 to 3/3, cost
  per run from $0.46 to $0.21.
  ([step 49](docs/step49_ci_eval_gate.md),
  [step 51 runbook](docs/step51_bad_trace_runbook.md))

## Repository layout

```
src/research_copilot/
  agents/          lead agent, subagents, tools, demos
  api/             FastAPI app
  evals/           capture, scoring, A/B, regression loop, CI gate
  observability/   OTel setup, identity propagation
collector/         OTel Collector config (redaction, span metrics, tail sampling)
grafana/           provisioned dashboard and alert rules
scripts/           load test, Phase 7/8 verification and prompt sync
data/              eval dataset and regression cases
docs/              per-step findings, progress tracker, reference notes
```

## Branching

One branch per phase or fix, cut from `develop` and merged back by PR.
`main` is updated at milestones (after Phases 1, 4 and 8).
