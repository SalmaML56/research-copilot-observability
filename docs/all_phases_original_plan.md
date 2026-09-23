# Complete Original Project Roadmap (Phases 0-8)

This is the full original plan from the project brief, kept here for
reference so it doesn't need to be re-typed each time.

## Phase 0 — Set up the ground
Branch: phase-0/observability-foundations
1. Scaffold folder structure.
2. Explain trace vs span, sketch a hypothetical trace.
3. Summarize OTel GenAI semantic conventions, cheat sheet of 10-15 attributes.
4. Run OTel Collector locally, confirm a test span prints.
5. Explain LangChain layers: LangGraph -> create_agent -> Deep Agents.
6. Write trace contract doc: session_id, user_id, prompt_version, environment, cost_usd.

## Phase 1 — Build the agent
Branch: phase-1/agent-core
7. uv add deepagents, build hello-world Deep Agent with web-search tool.
8. Add researcher + writer subagents.
9. Use built-in planner/filesystem, confirm todo list + notes saved.
10. Add checkpointer - SQLite first, then migrate to Postgres. Confirm resume-from-crash.
11. Add human-in-the-loop pause on one tool (e.g. publish_report).
12. Turn on streaming, print typed events.
13. Configure second, cheaper open-weight model as alternate harness profile.
14. Write test dataset: 20-30 research prompts in JSONL.

## Phase 2 — Get your first traces
Branch: phase-2/langfuse-tracing
15. Self-host Langfuse (docker compose up), create project, get API keys.
16. Attach Langfuse's CallbackHandler.
17. Add langfuse_session_id / langfuse_user_id to metadata.
18. Wrap custom tools with @observe.
19. Run 10 dataset prompts, manually review traces, write 3 findings.
20. Try LangGraph Studio - step through checkpoints, replay from any point.

## Phase 3 — Switch to OpenTelemetry
Branch: phase-3/opentelemetry-migration
21. Install OpenInference for LangChain, auto-convert to OTel spans.
22. Point OTLP exporter at Collector, confirm spans arrive.
23. Try OpenLLMetry too, compare span trees against OpenInference.
24. Add genai normalizer processor to standardize gen_ai.* attribute names.
25. Add manual spans for anything auto-instrumentation misses.
26. Deliberately break context propagation, observe split trace, fix it.
27. Send traces to Langfuse over OTLP directly, confirm parity with Phase 2.

## Phase 4 — Add a second backend + real APM stack
Branch: phase-4/apm-stack-integration
28. Self-host Arize Phoenix, point OpenInference exporter at it.
29. Compare Langfuse vs Phoenix on the same run, write comparison.
30. (Optional) Try Opik or MLflow 3.
31. Wrap agent in FastAPI endpoint (POST /research).
32. Stand up Grafana + Tempo + Prometheus + Loki (or SigNoz).
33. Find one full agent run in Grafana via Tempo, searching by session_id.

## Phase 5 — Metrics, dashboards, alerts
Branch: phase-5/metrics-dashboards-alerts
34. Verify gen_ai.client.token.usage and gen_ai.client.operation.duration land in Prometheus.
35. Compute cost (tokens x model price) via Collector transform processor or backend.
36. Build one Grafana dashboard: p50/p95 latency, tokens+cost per session,
    tool-call error rate, avg steps per run, subagent depth, checkpoint storage size.
37. Write five alerts: run >25 steps, cost spike 5x/hour, tool failure rate >10%,
    too many runs stuck on approval, checkpoint DB growing abnormally fast.
38. Add structured JSON logs with trace_id injected, confirm trace<->log jump works.

STATUS: DONE (completed by Ali via PR #29, merged into develop)

## Phase 6 — Evaluation
Branch: phase-6/evaluation-framework
38. Run offline evals with DeepEval or Ragas - LLM-as-judge on correctness/
    faithfulness, store scores as CSV + trace annotations.
39. Write trajectory scorers (searched before writing? repeated tool calls?
    exceeded step budget?).
40. Set up online evals on ~10% of live runs, write score back to trace.
41. Build failure -> dataset loop: tag bad traces, export, add corrected
    expectation to JSONL, re-run evals.
42. Run A/B test: frontier model vs open-weight model, chart cost vs quality.
43. Add human feedback (thumbs up/down on FastAPI response), post score to trace.

STATUS: DONE (merged into develop via PR #31)

## Phase 7 — Production-safe
Branch: phase-7/production-hardening

*** THIS IS WHERE THE POSTGRES DATABASE WORK BELONGS ***
*** We initially missed implementing this properly in Phase 1 - Postgres
    checkpointing was deferred and only SQLite was used. This was reviewed
    and the decision was made (see docs/step9_postgres_deferral_decision.md)
    that Postgres migration correctly belongs HERE in Phase 7, not Phase 1,
    per this original brief - so it was not a shortcut, just needed to be
    made explicit rather than silently skipped. ***

44. Add sampling: keep 100% of errored/expensive runs, sample 20% of rest
    (Collector tail-sampling processor).
45. Redact sensitive content (emails, phone numbers, keys) - opt-in per
    environment, off by default in prod.
46. *** Deploy on LangGraph Server (self-hosted) WITH POSTGRES CHECKPOINTS
    AND STREAMING *** - this is the actual Postgres migration step:
    - Add a dedicated Postgres service (or reuse langfuse-postgres with a
      separate database/schema)
    - Install langgraph-checkpoint-postgres
    - Swap SqliteSaver for PostgresSaver in checkpointed_agent.py
    - Verify resume-after-process-restart: start a run, pause it, kill the
      process entirely, start a new process, resume the same thread ID,
      confirm it picks up correctly
47. Load-test with 20 concurrent sessions, confirm no cross-session trace leakage.
48. Measure human-in-the-loop approval queue (time paused -> approved, rejection rate).

STATUS: NOT STARTED

## Phase 8 — Close the loop with CI
Branch: phase-8/ci-cd-pipeline
49. Add GitHub Actions job running evals on every PR, fail PR if avg score
    drops below threshold.
50. Version prompts (Langfuse or Phoenix prompt management), stamp version
    onto every trace.
51. Write a one-page runbook for diagnosing and fixing a bad trace end-to-end.

STATUS: NOT STARTED

## Stretch goals (optional, only after Phase 8)
1. Trace an MCP tool server with MCP semantic conventions.
2. Build a tiny live UI on the streaming events.
3. Write a final comparison doc: callback-based vs OTel-based tracing,
   Langfuse vs Phoenix.

## Phase 9 — Deliver
Branch: merge develop -> main before this phase
55. Push complete project to GitHub.
56. Share repository link.
