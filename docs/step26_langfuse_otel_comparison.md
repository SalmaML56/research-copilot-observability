# Step 26 — OTel-to-Langfuse (direct) vs CallbackHandler-based Comparison

Per the review action plan: "run one representative workflow via callbacks
and once via direct OTel, paths kept explicitly separate; compare
delegation, tools, model calls, identity metadata; document with real
evidence." Both paths were run in **separate processes** (per the existing
warning in both scripts).

## Path A — Langfuse CallbackHandler (`main_agent.py`)

Uses Langfuse's native `CallbackHandler`, passed via LangChain's
`config={"callbacks": [...]}`, with `langfuse_session_id`/`langfuse_user_id`
set in `metadata`.

**Task:** Research small modular nuclear reactors and write a report.
**Session:** `demo-session-001`, user `demo-user-salma`.

**Result (verified via Observations API v2):**
- 9 unique observation types captured: `SummarizationMiddleware.before_model`,
  `TodoListMiddleware.after_model`, `model`, `tools`, `ChatDeepSeek`
  (generation), `finalize_report`, `read_file`, `web_search`, `write_todos`.
- `session_id` and `user_id` correctly populated as `demo-session-001` /
  `demo-user-salma` on every observation queried.
- The run itself hit our Step 18/Finding-3 self-correction cap (researcher
  failed to write its notes file twice, agent stopped retrying per the
  2-attempt limit and reported the failure honestly) — a live confirmation
  that fix works, captured as a side effect of this test.

## Path B — Direct OTLP export to Langfuse (`run_otel_to_langfuse_demo.py`)

Uses OpenInference's `LangChainInstrumentor` with a standalone
`TracerProvider` exporting straight to Langfuse's OTLP endpoint
(`{LANGFUSE_HOST}/api/public/otel/v1/traces`, HTTP Basic auth), with our own
`IdentitySpanProcessor` added to set `session_id`/`user_id` as plain span
attributes (the same mechanism used for our Grafana Tempo traces).

**Task:** Same CAP theorem research task used throughout this review cycle.
**Session (intended):** `step26-direct-otel-ea4c6c`, user
`step26-direct-otel-user`.

**Result (verified via Observations API v2):**
- 10+ unique observation types captured, including `ChatDeepSeek`, `model`,
  `tools`, `writer`, `finalize_report`, `read_file`, `write_todos`,
  `task` — confirming full delegation, tool calls, and model calls DO
  arrive at Langfuse via this path, same as Path A.
- **`session_id` and `user_id` arrived as empty strings, not the values we
  set.** Confirmed with a direct endpoint test (`curl` with the same Basic
  auth) that the endpoint and authentication are both working correctly
  (HTTP 200) — this rules out an auth/connectivity problem. The data
  itself reaches Langfuse; only the identity attributes fail to populate.

## Root cause (verified against Langfuse's own docs)

Langfuse's OTLP ingestion only recognizes specific attribute names for
session/user grouping: **`session.id`** / **`user.id`** (dotted, OTel
GenAI-convention style) or the Langfuse-namespaced
**`langfuse.session.id`** / **`langfuse.user.id`** — not an arbitrary
custom attribute literally named `session_id` (underscore, no namespace),
which is what our `IdentitySpanProcessor` sets.

This is a **real, previously-unknown gap**: our identity propagation fix
(Steps 5/24) works correctly for our own OTel Collector → Grafana Tempo
path (verified there with `{ span.session_id != "" }` TraceQL queries),
but the exact same attribute name is silently ignored by Langfuse's OTLP
endpoint specifically, because Tempo indexes arbitrary attributes
generically while Langfuse's OTLP ingestion maps a small, specific set of
recognized names to its structured session/user fields.

## Comparison summary

| | Path A (CallbackHandler) | Path B (direct OTel) |
|---|---|---|
| Delegation/tools/model calls captured | Yes | Yes |
| `session_id`/`user_id` populated correctly | Yes | **No — arrives empty** |
| Mechanism | Langfuse-native callback, sets Langfuse fields directly | Generic OTel span attribute, name not recognized by Langfuse's OTLP mapping |

## Action / recommendation

Not fixed in this pass (flagging rather than silently leaving it for
someone to rediscover): if direct-OTel-to-Langfuse export is ever used in
production (currently it is only a comparison/demo script, not part of
the main FastAPI app's path — the app uses the Collector →
Grafana/Phoenix path), `IdentitySpanProcessor` would need either a
Langfuse-specific variant that also sets `session.id`/`user.id` (dotted)
or `langfuse.session.id`/`langfuse.user.id`, or a second span processor
registered only on OTel providers that export directly to Langfuse. The
Collector → Grafana/Tempo path used by the main application is unaffected
by this finding.
