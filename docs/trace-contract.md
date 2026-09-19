# Trace Contract

Every span in this project SHOULD carry these attributes:

| Attribute | Type | Set where |
|---|---|---|
| session_id | string | span attribute, set at request entry point, propagated to child spans |
| user_id | string | span attribute, same mechanism |
| prompt_version | string | span attribute, same mechanism |
| environment | string | span attribute (NOT an OTel Resource attribute) — see note below |
| cost_usd | float | NOT YET IMPLEMENTED — see "cost_usd" section below |

## How this is actually enforced (corrected)

**Previous version of this doc incorrectly claimed** a Collector processor
(from Phase 3, step 23) enforces these fields on every span. That was
false — Ali verified 71 real spans and found none of the five fields.
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

**Known remaining gap (not hidden):** the FastAPI HTTP root span and its
ASGI receive/send sub-spans do not carry these attributes, because
`FastAPIInstrumentor` starts that span before `set_identity()` runs
inside the route handler body. Agent/model/tool spans (the vast majority
of spans in a request) do carry them, verified via a live trace query
(see Steps 5/24 in `docs/progress.md`).

## Why `environment` is a span attribute, not a Resource attribute

OpenTelemetry's `Resource` (set once per process via
`Resource.create({...})` in `otel_setup.py`) currently only carries
`service.name`. `environment` is deliberately a **per-span** attribute
here (set by `IdentitySpanProcessor`) rather than a Resource attribute,
because in principle a single running process could serve requests for
more than one logical environment value (though this project doesn't
currently do that). This is a design choice, not an oversight — stating
it explicitly per review feedback rather than leaving it ambiguous.

## `cost_usd` — not yet implemented

`cost_usd` belongs to Step 34 ("Compute cost via a Collector transform
processor or in the backend") and has not been implemented in this
project yet. Listing it here as a contract requirement without
implementing it was part of the original inaccurate claim — it is now
explicitly marked pending rather than silently assumed done.

**Design note for whoever implements Step 34:** cost must be recorded
per individual model-call span (i.e., the specific `ChatDeepSeek` /
`ChatGroq` generation span whose token usage produced that cost), not
as one aggregate figure copied onto every span in a trace. If an
aggregate session-level or trace-level cost is also wanted, it should
be a separate, clearly-named attribute (e.g. `session_cost_usd_total`)
computed by summing the per-span values — not the same `cost_usd` field
repeated on parent/child spans, which would double-count if anything
ever sums `cost_usd` across a trace.
