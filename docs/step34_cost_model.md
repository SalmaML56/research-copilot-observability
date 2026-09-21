# Step 34 — cost model

Where cost is computed, what the rates are, when they were checked, and
which span attribute each one is keyed on.

## Where the number is produced

In the OTel Collector, by the `transform/cost` processor in
`collector/otel-collector-config.yaml`. Not in the app, and not in a
backend.

Reason for choosing the Collector: the arithmetic then applies to every
producer that ever exports through it — the FastAPI path, the CLI path, the
Phase 3 demo scripts — without any of them needing to know about prices. If
it lived in the app, a run started any other way would carry no cost at all.

The result is written to the span attribute **`gen_ai.usage.cost_usd`**.

### Naming

`review-v2.md` flagged a collision: an earlier version of the processor
wrote `gen_ai.usage.cost_usd` while `docs/trace-contract.md` and
`docs/otel-genai-cheatsheet.md` said `cost_usd`. Resolved in favour of
`gen_ai.usage.cost_usd`, because it sits in the same namespace as the
`gen_ai.usage.input_tokens` / `gen_ai.usage.output_tokens` attributes it is
derived from. The two docs were updated to match.

## Per-span, never aggregated

`docs/trace-contract.md` already specified this and the processor honours
it: every statement is guarded by
`where attributes["gen_ai.usage.input_tokens"] != nil`, which is only true
on an individual model-call span. Cost is never copied onto a parent span.

If it were, `sum(cost_usd)` over a trace would count the same dollars once
per ancestor. An aggregate session or trace figure, if ever wanted, belongs
in a separately named attribute computed by summing the per-span values.

**Verified live** on trace `78ffbbd5c40298d8648f2d9bd811a245`:

| Count | What |
|---|---|
| 26 | spans carrying `gen_ai.usage.cost_usd` |
| 26 | spans carrying `gen_ai.usage.input_tokens` |
| 26 | `ChatDeepSeek` model spans |

Three equal numbers is the check: cost appears on exactly the model spans
and nowhere else.

## The rate table

Rates are per token (USD), as of **2026-09-21**.

| Model (as it appears on spans) | Input $/token | Output $/token | Source |
|---|---|---|---|
| `deepseek-chat` | 0.00000027 | 0.0000011 | DeepSeek API pricing, cache-miss standard rate (\$0.27 / \$1.10 per 1M tokens) |
| `deepseek-flash` | 0.00000027 | 0.0000011 | Provider-side alias of `deepseek-chat`, priced identically — see the alias note below |
| `deepseek-reasoner` | 0.00000055 | 0.00000219 | DeepSeek API pricing (\$0.55 / \$2.19 per 1M tokens) |
| `openai/gpt-oss-20b` | 0.0000001 | 0.0000005 | Groq pricing for the open-weight 20B model (\$0.10 / \$0.50 per 1M tokens) |

Anything else is left **unpriced**: the processor sets
`gen_ai.usage.cost_model = "unpriced"` and writes no `cost_usd` at all,
rather than defaulting to zero. A silent zero would understate cost on every
dashboard and give no signal that a new model had appeared.

### Why the table is keyed on the span value, not on `.env`

`review-v2.md`, Addendum E, observed `gen_ai.request.model` reading
`deepseek-flash` on live spans while `.env` requested `deepseek-chat`.
Re-confirmed on this run — the provider returns its own alias.

Two consequences, both handled:

1. The rate table covers **both** spellings. Keying it on the configured
   name would have priced nothing at all.
2. `metrics_setup._resolve_model_name()` now prefers the model name the
   provider reported over the configured one. Before this fix, the
   `gen_ai.client.token.usage` metric was labelled `deepseek-chat` while the
   cost attribute on the span was keyed on `deepseek-flash`, so any panel
   joining the two would have matched nothing and quietly shown no data.

### Why each model needs its own row

The previous version of this processor hardcoded DeepSeek rates with no
model condition. Every run on the `cheap` (Groq) profile would have been
priced as DeepSeek — roughly 2.7x the real input cost and 2.2x the real
output cost. Step 42's whole point is a cost-versus-quality comparison
between a frontier and an open-weight model; with one shared rate that
comparison would have been meaningless while still looking plausible.

## Arithmetic check

From the live trace, one `ChatDeepSeek` span:

```
gen_ai.request.model      = "deepseek-flash"
gen_ai.usage.input_tokens = 6159
gen_ai.usage.output_tokens= 563
gen_ai.usage.cost_usd     = 0.00228223
gen_ai.usage.cost_model   = "deepseek-flash"
```

By hand:

```
6159 * 0.00000027 = 0.00166293
 563 * 0.0000011  = 0.00061930
                    ----------
                    0.00228223
```

Exact match to the eighth decimal place.

## Keeping this honest

Prices change and an undated hardcoded rate becomes a silent lie. When the
table is next revised, update the as-of date at the top of the rate table
in the same commit as the Collector config, and redo the arithmetic check
above against a fresh span.
