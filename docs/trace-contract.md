# Trace Contract

Every span in this project SHOULD carry these attributes:

| Attribute | Type | Set where |
|---|---|---|
| session_id | string | span attribute, set at request entry point, propagated to child spans |
| user_id | string | span attribute, same mechanism |
| prompt_version | string | span attribute, same mechanism. Value from `agents/prompt_registry.py` (Step 50): `lead=N,researcher=N,writer=N` Langfuse versions, or `local-<hash>` per role when not synced |
| environment | string | span attribute (NOT an OTel Resource attribute) — see note below |
| gen_ai.usage.cost_usd | float | model-call spans only — set by the Collector's `transform/cost` processor (Step 34) |

## How this is actually enforced (corrected)

**Previous version of this doc incorrectly claimed** a Collector processor
(from Phase 3, step 23) enforces these fields on every span. That was
false — a review of 71 real spans found none of the five fields present.
The Collector's `gen_ai_normalizer` processor only **renames** existing
attributes (e.g. `gen_ai.system` → `gen_ai.provider.name`); it does not
add new ones.

The real mechanism, fixed in Steps 5/24: `IdentitySpanProcessor`
(`src/research_copilot/observability/identity.py`), registered on the
`TracerProvider` in `otel_setup.py`. It reads a `contextvars.ContextVar`
(set via `set_identity()`, called at the top of each FastAPI request
handler) and stamps `session_id`, `user_id`, `prompt_version`, and
`environment` onto every span as it starts — this happens entirely in
the Python SDK, not in the OTel Collector.

**Root span gap — closed in Phase 5.** The FastAPI HTTP root span used to
carry none of these attributes, because `FastAPIInstrumentor` starts it
before `set_identity()` runs inside the route handler body, and
`IdentitySpanProcessor.on_start` only fires for spans started afterwards.
`_begin_request()` in `api/main.py` now stamps the four attributes directly
onto the current span, which *is* the still-open root span at that point.

Verified on trace `78ffbbd5c40298d8648f2d9bd811a245`: the root
`POST /research` span carries `session_id`, `user_id` (a real value, not
`"unknown"`), `prompt_version` and `environment`.

**Still not covered, stated rather than hidden:** the ASGI
`http send` / `http receive` sub-spans. Three spans out of 202 on that
trace. They are created by the ASGI middleware outside the handler body and
represent framework plumbing, not agent work.

## Why `environment` is a span attribute, not a Resource attribute

OpenTelemetry's `Resource` (set once per process via
`Resource.create({...})` in `otel_setup.py`) currently only carries
`service.name`. `environment` is deliberately a **per-span** attribute
here (set by `IdentitySpanProcessor`) rather than a Resource attribute,
because in principle a single running process could serve requests for
more than one logical environment value (though this project doesn't
currently do that). This is a design choice, not an oversight — stating
it explicitly per review feedback rather than leaving it ambiguous.

## `gen_ai.usage.cost_usd` — implemented in Phase 5, Step 34

Computed in the OTel Collector by the `transform/cost` processor in
`collector/otel-collector-config.yaml`, and written to the span attribute
**`gen_ai.usage.cost_usd`**.

### Name

An earlier draft of this doc called the field `cost_usd` while the
Collector wrote `gen_ai.usage.cost_usd`. Resolved in favour of
`gen_ai.usage.cost_usd`: it belongs in the same namespace as the
`gen_ai.usage.input_tokens` / `gen_ai.usage.output_tokens` attributes it is
derived from. `docs/otel-genai-cheatsheet.md` was updated to match.

### Per-span, never aggregated

The design note this doc carried before Step 34 was implemented has been
honoured. Every cost statement is guarded by
`where attributes["gen_ai.usage.input_tokens"] != nil`, which is true only
on an individual model-call span. Cost is never copied onto a parent, so
summing it across a trace cannot double-count.

Verified live on trace `78ffbbd5c40298d8648f2d9bd811a245`: 26 spans carry
`gen_ai.usage.cost_usd`, 26 carry `gen_ai.usage.input_tokens`, and there
are exactly 26 `ChatDeepSeek` model spans.

If a trace- or session-level total is ever wanted, it must be a separately
named attribute (e.g. `session_cost_usd_total`) computed by summing the
per-span values — never the same field repeated up the tree.

### Unpriced models are marked, not zeroed

A model with no entry in the rate table gets
`gen_ai.usage.cost_model = "unpriced"` and no `cost_usd` at all. Defaulting
to zero would understate cost on every dashboard while looking like a
legitimate reading.

Rates, sources, as-of date and the arithmetic check:
`docs/step34_cost_model.md`.

## Span attribute limit

`TracerProvider` is created with
`SpanLimits(max_span_attributes=2048)` (override with
`OTEL_SPAN_ATTRIBUTE_COUNT_LIMIT`).

This is load-bearing for the contract above, not a tuning detail. The SDK
default is 128 attributes per span, and OpenInference flattens each chat
message into several attributes, so long-context model spans overflowed.
On overflow the Python SDK evicts the **oldest** attributes first, and
`IdentitySpanProcessor.on_start` writes before anything else — so identity
was the first thing discarded, on precisely the largest and most expensive
model calls. Measured before the fix: 10 of 349 spans had lost all four
identity attributes, and every one of them had `droppedAttributesCount > 0`.

After the fix, on a 202-span run: **0 spans with dropped attributes**, and
199 of 202 carrying `session_id`.
