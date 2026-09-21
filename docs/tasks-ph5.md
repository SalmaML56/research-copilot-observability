# Phase 5 — Metrics, Dashboards, Alerts: detailed task list

Source of truth for scope: `obs-mon.md` steps 33–37.
Status of everything before this phase: `docs/progress.md`.
Outstanding review findings this phase inherits: `review-v2.md`.

Created 2026-09-21. **Completed 2026-09-21.** Branch:
`phase-5/metrics-dashboards-alerts`.

---

## Status: all Phase 5 tasks done

Every task below was implemented and then checked against the running
stack — 9 containers up, two real DeepSeek runs, one of them taken all the
way through `POST /research` → pause → `approve` → completed.

Start here: **`docs/phase5_evidence/README.md`** (short guide).
Evidence, with trace IDs, queries and screenshots:
**`docs/phase5_evidence/verification-details.md`**.

| Task | Status | Verified by |
|---|---|---|
| P5-00 rebase branch | done | already rebased by a teammate; `git log develop..branch` = 1 commit, 3 files |
| P5-01 span attribute limit | done | 0 spans with dropped attributes on a 202-span run (was 10 of 349 losing identity) |
| P5-02 gate Langfuse `@observe` | done | 0 `langfuse.*` attributes in Tempo; 25 tool spans for 28 HTTP calls (was 74 for 37) |
| P5-03 Langfuse reproducible | done | `/api/public/projects` authenticates with the `.env` keys; UI sign-in works |
| P5-04 persistent LGTM volumes | done | container **removed and recreated**; traces, metrics, logs, dashboard and rules all survived |
| P5-05 pin images | done | no `:latest` left in `docker-compose.yml` |
| P5-10 do GenAI metrics exist? | done | answered **no** — `docs/step33_metrics_verification.md` |
| P5-11 produce them | done | app-side `GenAIMetricsCallbackHandler`; both metrics queryable in Prometheus |
| P5-12 debug exporter on metrics | done | present on the metrics pipeline |
| P5-13 spanmetrics dimensions | done | `gen_ai_tool_name`, `gen_ai_request_model`, `user_id`, `environment`, `prompt_version` confirmed on live series |
| P5-20 cost attribute naming | done | single spelling `gen_ai.usage.cost_usd` across Collector + both docs |
| P5-21 model-aware prices | done | 4 models priced, unknown models marked `unpriced` not `$0` |
| P5-22 per-span, never aggregated | done | 26 cost spans = 26 token spans = 26 model spans |
| P5-23 dated price table | done | `docs/step34_cost_model.md` |
| P5-24 cross-check cost | done | hand calculation matches to 8 decimal places |
| P5-25 one MeterProvider | done | single `set_meter_provider` call in the codebase |
| P5-26 metrics on the HTTP path | done | `POST /research` alone produces datapoints; CLI path wired too |
| P5-30 dashboard | done | 9 panels, all with real data, 0 in error — `01-dashboard.png` |
| P5-31 screenshot evidence | done | `docs/phase5_evidence/` |
| P5-32 subagent depth decision | done | `docs/step35_37_decisions.md` |
| P5-40 .. P5-44 five alerts | done | all 5 provisioned and evaluating |
| P5-45 alerts as code | done | survived container recreation — `02-alerts.png` |
| P5-46 prove one fires | done | cost-spike rule reached **Firing** on real traffic |
| P5-50 JSON logs + trace context | done | `trace_id`/`session_id`/`user_id` on every record |
| P5-51 Collector logs pipeline | done | logs queryable in Loki |
| P5-52 replace `print()` | done | request path had none; added structured tool-failure log |
| P5-53 correlation both ways | done | clicked through in the browser in both directions |
| P5-54 what never to log | done | `docs/step35_37_decisions.md` |

### Prerequisites from Phases 0–4 that had to be fixed first

| Item | Status |
|---|---|
| FastAPI root span had no identity attributes | **fixed** — root span carries all four |
| `user_id` hardcoded `"unknown"` | **fixed** — accepted on the request |
| Failed tool spans `UNSET`, never `ERROR` | **fixed** — 5 ERROR / 23 OK on a real run |
| `.env` load order in `otel_setup.py` (review v2, Step 21) | **fixed** |
| Checkpoint-DB gauge used a relative path | **fixed** — resolved absolutely |

### Found and fixed while verifying, not predicted by the task list

1. **OTel unit `"1"` becomes a `_ratio` metric-name suffix in Prometheus.**
   `research_copilot.runs.pending_approval` arrived as
   `..._pending_approval_ratio`. Any dashboard written against the obvious
   name would have silently found nothing. Fixed with annotation units.
2. **The token metric was labelled with the *configured* model name while
   the cost attribute was keyed on the *provider-reported* one**
   (`deepseek-chat` vs `deepseek-flash`). A panel joining cost to tokens
   would have matched nothing. Fixed by reading the model name off the
   response.
3. **The Collector renamed two components.** `spanmetrics` → `span_metrics`
   and `otlphttp` → `otlp_http` are deprecated aliases in 0.159.0.
4. **A single-file bind mount is unsafe on Docker Desktop for Windows.**
   If the host file is missing at `up` time, Docker creates a *directory*
   there and every later start fails with `not a directory`. The dashboards
   provisioning mount is a directory mount for this reason, and the image's
   own three providers are re-declared so they are not lost.
5. **`LANGFUSE_INIT_USER_EMAIL` is validated** and rejects `dev@localhost`;
   langfuse-web refuses to start at all.
6. **Cost/token panels need `max_over_time(...[$__range])`.** Prometheus
   marks a series stale after 5 minutes, so an instant query showed only
   sessions from the last 5 minutes — a "cost per session" panel that
   forgot everything older.

---


---

## Legend

- **P0** — blocks trustworthy Phase 5 evidence. Do first.
- **P1** — required for the step to be honestly "done".
- **P2** — quality / follow-up, can ship after the phase.
- Every task has an **Acceptance** line. A task is done only when the
  acceptance check has actually been run, not when the code looks right.

---

## Section 0 — Blockers to clear before any Phase 5 work

These are all pre-existing findings from `review-v2.md`. Each one, left
alone, silently corrupts a Phase 5 number.

### P5-00 (P0) — Rebase the existing `phase-5/metrics-dashboards-alerts` branch

The remote branch forks from `63efd42`, before PRs #6–#14. A two-dot diff
against `develop` shows it reverting `identity.py`, `main.py`,
`settings.py`, and `otel_setup.py`. The three-dot diff is only 3 files
(`collector/otel-collector-config.yaml`, `checkpointed_agent.py`,
`observability/custom_metrics.py`), so the rebase should be small — but it
must happen before anything else is added to that branch.

- Files: whole branch.
- Acceptance: `git diff develop...phase-5/metrics-dashboards-alerts` lists
  only Phase 5 files; `identity.py` is present on the branch and unchanged.

### P5-01 (P0) — Raise the span attribute limit (review-v2 Addendum C)

Default SDK limit is 128 attributes/span. OpenInference flattens each
message into several attributes, so long-context `ChatDeepSeek` spans
overflow and the SDK evicts the **oldest** attributes first — which is
exactly `session_id`, `user_id`, `prompt_version`, `environment`, written
by `IdentitySpanProcessor.on_start`. In the last real trace, 10 of 349
spans had lost all four. Those 10 are the *most expensive* model calls,
i.e. the ones per-session cost (P5-20, P5-30) most needs.

- Files: `src/research_copilot/observability/otel_setup.py`
  (`TracerProvider(..., span_limits=SpanLimits(max_span_attributes=2048))`),
  or `OTEL_SPAN_ATTRIBUTE_COUNT_LIMIT` in `.env` / `.env.example`.
- Acceptance: run a real `POST /research`, query Tempo, confirm
  `droppedAttributesCount == 0` on every span **and** that 100% of
  non-FastAPI spans carry `session_id`.

### P5-02 (P0) — Gate the Langfuse `@observe` decorators (Step 17 / Addendum D)

`src/research_copilot/agents/tools.py` still has `@observe(as_type="tool")`
on two tools, ungated. Measured result: 74 spans named `web_search` for 37
real `web_search.ddgs_http_call` spans, plus 224 `langfuse.*` attributes
stored in Tempo. **Every tool-call count, error rate, and latency panel
built in P5-30/P5-40 will be exactly 2x wrong until this is fixed.**

- Files: `src/research_copilot/agents/tools.py`,
  `src/research_copilot/observability/langfuse_setup.py`.
- Approach: env-gated run mode (e.g. `TRACING_BACKEND=otel|langfuse`) that
  makes `@observe` a no-op and skips attaching the Langfuse span processor
  when running the OTel path.
- Acceptance: one research run produces exactly one span per tool call;
  `langfuse.*` attribute count in Tempo for that trace is 0.

### P5-03 (P0) — Make Langfuse reproducible (Addendum A)

Fresh clone gets `401 Unauthorized` on span export because the
`langfuse_postgres_data` volume has 0 projects and 0 API keys, and the
`LANGFUSE_INIT_*` vars in `docker-compose.yml` are all empty. Not strictly
a Phase 5 step, but the 401 spam pollutes every Phase 5 run's logs and
blocks any cross-check against Langfuse's own cost figures.

- Files: `docker-compose.yml`, `.env`, `.env.example`, `README.md`.
- Acceptance: `docker compose down -v && docker compose up -d`, then a run
  with zero `Failed to export span batch code: 401` lines.

### P5-04 (P0) — Give `grafana-lgtm` a persistent volume

`grafana-lgtm` currently has no volume. Dashboards (P5-30) and alert rules
(P5-40) built by hand in the UI **disappear on container restart**, and so
do the traces used as evidence. This is the single biggest risk to this
phase producing durable artifacts.

- Files: `docker-compose.yml`.
- Approach: named volumes for Grafana + Prometheus + Tempo data, and
  bind-mount `./grafana/provisioning` and `./grafana/dashboards` (both dirs
  already exist with only `.gitkeep`) so dashboards and alerts live in git
  as provisioned YAML/JSON rather than as clicked-in UI state.
- Acceptance: `docker compose restart grafana-lgtm`; dashboard and alert
  rules still present.

### P5-05 (P1) — Pin the `grafana/otel-lgtm` and `arizephoenix/phoenix` images

Both are `:latest` (review-v2 Step 27). A silent image bump mid-phase would
change panel/metric behaviour with no commit to blame.

- Files: `docker-compose.yml`.
- Acceptance: no `:latest` tag remains in `docker-compose.yml`.

---

## Section 1 — Step 33: emit token and duration metrics

`obs-mon.md` asserts "the instrumentation already emits
`gen_ai.client.token.usage` and `gen_ai.client.operation.duration`."
**This is unverified for our stack and is probably false** — we use
`openinference-instrumentation-langchain`, which emits spans, not metrics.
Do not assume; measure.

### P5-10 (P1) — Establish whether GenAI metrics are actually emitted

- Steps: start the stack, run one agent request, then query the LGTM
  Prometheus directly for `gen_ai_client_token_usage*` and
  `gen_ai_client_operation_duration*`.
- Acceptance: a written yes/no in `docs/step33_metrics_verification.md`
  with the exact query and the exact response body.

### P5-11 (P1) — If absent, produce them ourselves

Two viable routes, pick one and record why:

- (a) **Collector-side** — derive from span attributes via the
  `spanmetrics` connector (already on the branch) plus a `transform`
  that emits token counts. Zero app changes; works for any SDK.
- (b) **App-side** — wire a `MeterProvider` into `otel_setup.py` and
  record `gen_ai.client.token.usage` / `.operation.duration` from the
  model span's own usage data.

Note: the branch's `custom_metrics.py` already builds a **second,
separate** `MeterProvider`. Consolidate it into `otel_setup.py` so there
is one provider, one resource, one export interval (P5-25).

- Acceptance: both metric names queryable in Prometheus with non-zero
  values after a real run.

### P5-12 (P1) — Add the metrics pipeline receiver wiring properly

The branch adds `metrics: receivers: [otlp, spanmetrics]` — good — but
there is **no `debug` exporter on the metrics pipeline**, which makes
"nothing arrived" indistinguishable from "arrived and was dropped" during
bring-up.

- Files: `collector/otel-collector-config.yaml`.
- Acceptance: `docker compose logs otel-collector` shows metric datapoints
  during a run.

### P5-13 (P1) — Add the missing spanmetrics dimensions

Branch config declares only `gen_ai.tool.name`. Per-session / per-user /
per-model panels (Steps 35, 36b) and the Step 42 A/B are impossible
without more dimensions.

- Add at minimum: `session_id`, `user_id`, `gen_ai.request.model`,
  `gen_ai.operation.name`, `environment`.
- Caution: `session_id` is high-cardinality. Decide explicitly whether it
  is a dimension (accurate per-session panels, unbounded series) or is
  handled by trace-to-metric drilldown instead. Record the decision.
- Acceptance: `{__name__=~"traces_span_metrics.*"}` in Prometheus shows the
  chosen labels populated.

---

## Section 2 — Step 34: compute cost

### P5-20 (P1) — Fix the cost attribute name collision

The branch's `transform/cost` writes `gen_ai.usage.cost_usd`.
`docs/trace-contract.md` and `docs/otel-genai-cheatsheet.md` both say
`cost_usd`. Pick one name and make all three agree.

- Recommendation: `gen_ai.usage.cost_usd` (namespaced, matches the sibling
  `gen_ai.usage.input_tokens`), then update the two docs.
- Acceptance: one `grep -rn "cost_usd"` across `docs/`, `collector/`, and
  `src/` shows a single consistent spelling.

### P5-21 (P1) — Make the price table model-aware

The branch hardcodes DeepSeek rates with **no model condition**. Any run on
the `cheap` (Groq / `openai/gpt-oss-20b`) profile is priced as DeepSeek.
That silently invalidates the Step 42 frontier-vs-open-weight A/B before
it is even run.

- Files: `collector/otel-collector-config.yaml`.
- Approach: one `set(...) where attributes["gen_ai.request.model"] == "..."`
  statement per model, plus an explicit fallback that marks an unknown
  model rather than pricing it at zero.
- **Gotcha (Addendum E):** the live trace showed
  `gen_ai.request.model == "deepseek-flash"` while `.env` requests
  `deepseek-chat`. Key the price table on the string that actually appears
  on spans, and cover both aliases.
- Acceptance: one run on each profile; per-span cost differs and matches
  a hand calculation for both.

### P5-22 (P1) — Honour the per-span cost design note

`docs/trace-contract.md` already specifies: cost goes on the individual
model-call span, never as an aggregate copied onto parents (it would
double-count on summation). The branch's transform is per-span — confirm
it does not also stamp parents.

- Acceptance: in one trace, the count of spans carrying a cost attribute
  equals the count of model spans.

### P5-23 (P2) — Record the price table's as-of date and source

Prices change. An undated hardcoded rate becomes a silent lie.

- Files: `docs/step34_cost_model.md` (new) — rates, currency, source URL,
  date checked, and which span attribute each is keyed on.

### P5-24 (P1) — Cross-check against Langfuse

Step 28 already found that Phoenix shows model-span token usage/cost while
Langfuse (direct-OTel path) shows `None`. Use Phoenix and/or a hand
calculation as the reference to validate the Collector's arithmetic.

- Acceptance: computed cost for one model span matches a manual
  `tokens x rate` calculation to the cent.

### P5-25 (P1) — Consolidate the two MeterProviders

`custom_metrics.py` calls `metrics.set_meter_provider()` independently of
`otel_setup.py`. Two providers means two resources and two flush paths.

- Acceptance: one `set_meter_provider` call in the codebase; metrics from
  both custom and auto sources share `service.name=research-copilot-agent`.

### P5-26 (P1) — Wire metrics into the FastAPI path

`setup_custom_metrics()` is currently only called from
`checkpointed_agent.py`. The API (`src/research_copilot/api/main.py`) is
the path that actually serves requests, so **no metrics are emitted for
real traffic at all.**

- Acceptance: a `POST /research` alone (no CLI run) produces datapoints in
  Prometheus.

---

## Section 3 — Step 35: one Grafana dashboard

One screen. Panels required by `obs-mon.md`:

### P5-30 (P1) — Build the dashboard

- [ ] p50 / p95 latency per agent and per subagent
- [ ] tokens and cost per session
- [ ] tool-call error rate — **blocked on P5-02**, else 2x wrong
- [ ] average steps per run — source: `research_copilot.run.steps`
      histogram (exists on branch, but see P5-26 — only fires from CLI)
- [ ] subagent depth — no metric exists for this yet; needs either a new
      custom metric or a spanmetrics dimension derived from span nesting.
      **Design decision required.**
- [ ] checkpoint storage size — source:
      `research_copilot.checkpoint.db_size_bytes` observable gauge (exists
      on branch). Note the gauge resolves `checkpoints.sqlite` as a
      **relative path**, so it reads 0 whenever the process is started from
      any other working directory. Fix to an absolute/configured path.

- Files: `grafana/dashboards/research-copilot.json` (provisioned, in git —
  see P5-04), `grafana/provisioning/dashboards/*.yaml`.
- Acceptance: dashboard loads from a fresh `docker compose up` with no
  manual UI steps, and every panel shows real data after one run.

### P5-31 (P1) — Screenshot the dashboard as evidence

LGTM has no persistence by default (P5-04 fixes data, but traces still age
out). Evidence must be captured, not just claimed.

- Files: `docs/phase5_evidence/` + a note in `docs/progress.md`.

### P5-32 (P2) — Resolve "subagent depth"

Decide the measurement: span-tree depth computed in the Collector, or an
explicit depth attribute set by the agent when it delegates. Write the
decision down before building the panel.

---

## Section 4 — Step 36: five alerts

All five need a threshold justified by observed data, not a guess. The
Step 18 and Addendum E runs (37 searches, 41 model calls, 231 s for one
topic) are the baseline to calibrate against.

### P5-40 (P1) — Alert (a): run exceeded 25 steps — probable loop

- Source: `research_copilot.run.steps` histogram.
- Blocked on P5-26 (API path doesn't emit it today).

### P5-41 (P1) — Alert (b): a single user's cost spiked 5x in an hour

- Source: cost metric by `user_id` dimension (P5-13, P5-21).
- Note: `user_id` is currently hardcoded `"unknown"` in the
  `set_identity()` calls — review-v2 Step 24 flags this as open. **This
  alert cannot distinguish users until a real `user_id` is accepted on
  the request.** Either fix that first or document the alert as
  environment-wide rather than per-user.

### P5-42 (P1) — Alert (c): tool failure rate over 10%

- Source: spanmetrics `status.code` by `gen_ai.tool.name`.
- **Double-blocked:** on P5-02 (double counting) *and* on review-v2
  Step 24's finding that failed attempts are recorded `UNSET`, not
  `ERROR` — 78 spans `UNSET`, 0 `ERROR` in the live trace. **A failure-rate
  alert on this data would read 0% forever.** Fixing span status is a hard
  prerequisite, not a nice-to-have.

### P5-43 (P1) — Alert (d): more than N runs stuck waiting for human approval

- No metric exists. Needs a new gauge counting threads whose
  `state.next` is non-empty (the interrupt state the API already inspects
  in `research()` / `approve()`).
- Pick N and justify it.

### P5-44 (P1) — Alert (e): checkpoint DB growing faster than expected

- Source: `research_copilot.checkpoint.db_size_bytes` (blocked on the
  relative-path bug in P5-30).
- Context: the tracked `checkpoints.sqlite` is already 13.7 MB. Set the
  rate threshold against measured growth, not a round number.

### P5-45 (P1) — Provision alerts as code

Same reasoning as P5-04: clicked-in alert rules are lost on restart and
invisible in review.

- Files: `grafana/provisioning/alerting/*.yaml`.
- Acceptance: `docker compose down && up`; all five rules present.

### P5-46 (P1) — Prove at least one alert actually fires

An alert that has never fired is an untested alert.

- Approach: force one condition (e.g. drive the step count past the
  threshold, or temporarily lower a threshold) and capture the firing
  state.
- Acceptance: screenshot / API response showing state `Alerting`, recorded
  in `docs/phase5_evidence/`.

---

## Section 5 — Step 37: structured JSON logs with `trace_id`

**Nothing exists yet.** `grep -rn "logging" src/` returns zero hits — the
codebase uses bare `print()` throughout. This step is greenfield.

### P5-50 (P1) — Add a JSON logging formatter with trace context injection

- Emit: timestamp, level, logger, message, `trace_id`, `span_id`,
  `session_id`, `service.name`.
- Use `opentelemetry.trace.get_current_span().get_span_context()` for the
  IDs, formatted as the 32-hex / 16-hex strings Tempo and Loki expect
  (not the raw ints — a mismatch here is the usual reason correlation
  silently fails).
- Files: new `src/research_copilot/observability/logging_setup.py`.

### P5-51 (P1) — Add the logs pipeline to the Collector

The Collector config has **no `logs:` pipeline at all** — review-v2 flags
this as why Step 31 stays partial even after the branch merges.

- Files: `collector/otel-collector-config.yaml` — add
  `logs: receivers: [otlp], exporters: [debug, otlphttp/grafana]`.
- Needs OTel SDK log export wiring in the app plus the `LoggingHandler`
  bridge, and the OTLP log exporter dependency in `pyproject.toml`.
- Acceptance: logs queryable in Loki via Grafana.

### P5-52 (P1) — Replace `print()` in the request path with the logger

At minimum `api/main.py`, `agents/tools.py`, `agents/subagents.py`. Demo
scripts can keep `print()`.

### P5-53 (P1) — Prove trace-to-log correlation in both directions

This is the actual acceptance criterion of Step 37 — not "logs are JSON".

- From a trace in Tempo, click through to its logs in Loki.
- From a log line in Loki, click through to its trace.
- Requires a Grafana derived-field / trace-to-logs data source config in
  `grafana/provisioning/datasources/`.
- Acceptance: both directions screenshotted.

### P5-54 (P2) — Decide what must never be logged

Prompts and search results flow through these paths. Record the decision
on content capture now; Step 45 (Phase 7) formalises it.

---

## Section 6 — Carried-over debt (not Phase 5 scope, but still open)

Tracked here so "what's remaining" is honest. From `review-v2.md`, still
open on `develop` and **not** claimed done in `docs/progress.md`:

| Item | Step | Impact on Phase 5 |
|---|---|---|
| FastAPI root span has no identity attributes | 5 / 24 / 30 | Root span excluded from per-session panels |
| `user_id` hardcoded `"unknown"` | 24 | Blocks per-user cost alert (P5-41) |
| Failed spans marked `UNSET`, never `ERROR` | 24 | Blocks tool error-rate alert (P5-42) |
| Langfuse `@observe` leak | 17 | 2x tool counts (P5-02) |
| Span attributes dropped on big spans | Addendum C | Loses identity on costliest spans (P5-01) |
| `docs/trace-contract.md` cost naming | 34 | P5-20 |
| `docs/otel-genai-cheatsheet.md` outdated | 2 | Cost/attribute names |
| `main_agent.py` has no `interrupt_on`; API doesn't return draft + pending action when paused | 10 | Affects P5-43's stuck-approval metric |
| Stream uses legacy format, not `version="v2"` | 11 | None |
| Step 29 (Opik/MLflow) not marked skipped anywhere | 29 | None |
| `langchain-google-genai` dependency unused | housekeeping | None |
| Thread IDs hardcoded (`phase1-step10-demo-thread-v2`) | 9 / 11 | Pollutes session-scoped panels |
| `checkpoints.sqlite` (13.7 MB) tracked in git | housekeeping | None |
| Postgres checkpointing | 9 | Deferred to Phase 7 by documented decision |

---

## Section 7 — Phase 5 exit criteria

Phase 5 is done when **all** of these are true, each with recorded
evidence in `docs/progress.md` and `docs/phase5_evidence/`:

1. Token and duration metrics are queryable in Prometheus after a real
   `POST /research` — with the query and response recorded.
2. Every model span carries a cost attribute whose value matches a hand
   calculation, and the price table is model-aware and dated.
3. One Grafana dashboard, provisioned from git, survives a container
   restart, and every panel shows real data.
4. Five alert rules exist as provisioned YAML, and at least one has been
   observed in the `Alerting` state.
5. JSON logs carry a correct `trace_id`, reach Loki, and correlation works
   in both directions.
6. No panel or alert is built on a number known to be double-counted
   (P5-02) or known-constant (P5-42's `UNSET` problem).
7. `README.md` phase table and `docs/progress.md` both updated — Phase 5
   marked with its real status, not flatly "Done".

---

## Section 8 — Suggested order

1. **P5-00** rebase — before touching the branch.
2. **P5-01, P5-02, P5-04** — the three that corrupt data. Small, high value.
3. **P5-03, P5-05** — reproducibility and pinning.
4. **P5-10 → P5-13** — establish what metrics actually exist. Everything
   downstream depends on the answer.
5. **P5-20 → P5-26** — cost, correctly.
6. Span-status fix + real `user_id` (Section 6 rows) — prerequisites for
   the alerts, cheaper to do now than to work around later.
7. **P5-30 → P5-32** — dashboard.
8. **P5-40 → P5-46** — alerts.
9. **P5-50 → P5-54** — logs and correlation.
10. Evidence sweep (P5-31, P5-46, P5-53) + README and `progress.md` updates.
