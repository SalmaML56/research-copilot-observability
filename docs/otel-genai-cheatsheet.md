# OTel GenAI Semantic Conventions — Cheat Sheet

Following OTel GenAI semantic conventions **v1.37.0** (status: Development,
not yet marked stable — attribute names may still change in future
releases). Verified against the live spans this project actually emits
(Step 22 comparison run) as well as the official spec.

| Attribute | Meaning |
|---|---|
| gen_ai.provider.name | Provider/framework, e.g. "openai", "deepseek" (renamed from `gen_ai.system`) |
| gen_ai.request.model | Model requested |
| gen_ai.response.model | Model that actually answered |
| gen_ai.request.temperature | Sampling temperature |
| gen_ai.request.max_tokens | Max tokens requested |
| gen_ai.usage.input_tokens | Prompt tokens consumed |
| gen_ai.usage.output_tokens | Completion tokens produced |
| gen_ai.agent.name | Which agent/subagent ran this span |
| gen_ai.tool.name | Which tool was called |
| gen_ai.tool.call.id | Correlates a tool call to its result |
| gen_ai.operation.name | e.g. "chat", "execute_tool", "create_agent", "invoke_agent" |
| gen_ai.input.messages | Full input messages (PII risk) — renamed from `gen_ai.prompt` |
| gen_ai.output.messages | Full output messages (PII risk) — renamed from `gen_ai.completion` |
| gen_ai.conversation.id | Unique ID for a conversation/session/thread — see note below |

## Renames vs older conventions (pre-1.37.0)

| Old name | Current name (v1.37.0) |
|---|---|
| gen_ai.system | gen_ai.provider.name |
| gen_ai.prompt | gen_ai.input.messages |
| gen_ai.completion | gen_ai.output.messages |

## gen_ai.conversation.id vs our session_id

`gen_ai.conversation.id` is OTel's standard attribute for grouping spans
within one conversation/thread. This project's own trace contract (see
below) independently defines `session_id` for the same purpose, set via
our `IdentitySpanProcessor` (Steps 5/24).

These are **not currently the same attribute** — `session_id` is our
project-specific field, `gen_ai.conversation.id` is the OTel-standard one.
Both end up meaning "which conversation does this span belong to." A
future improvement would be to either also emit `gen_ai.conversation.id`
set to the same value as our `session_id`, or migrate to using
`gen_ai.conversation.id` directly instead of a custom field, for better
interoperability with tools that only understand the standard OTel name.
Not done in this pass — flagged here rather than assumed already handled.

## Project-specific additions (required by our trace contract)
| session_id | Groups spans from one conversation (project-specific; see note above re: gen_ai.conversation.id) |
| user_id | Who triggered the run |
| prompt_version | Which prompt template version |
| environment | dev / staging / prod |
| gen_ai.usage.cost_usd | tokens x price, set per model-call span by the Collector's `transform/cost` processor (Step 34). Rates and as-of date: `docs/step34_cost_model.md`. |
| gen_ai.usage.cost_model | the model name the price was looked up under, or `unpriced` when no rate matched |
