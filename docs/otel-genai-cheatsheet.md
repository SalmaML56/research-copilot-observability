# OTel GenAI Semantic Conventions — Cheat Sheet

| Attribute | Meaning |
|---|---|
| gen_ai.system | Provider/framework, e.g. "openai" |
| gen_ai.request.model | Model requested |
| gen_ai.response.model | Model that actually answered |
| gen_ai.request.temperature | Sampling temperature |
| gen_ai.request.max_tokens | Max tokens requested |
| gen_ai.usage.input_tokens | Prompt tokens consumed |
| gen_ai.usage.output_tokens | Completion tokens produced |
| gen_ai.agent.name | Which agent/subagent ran this span |
| gen_ai.tool.name | Which tool was called |
| gen_ai.tool.call.id | Correlates a tool call to its result |
| gen_ai.operation.name | e.g. "chat", "tool.execution" |
| gen_ai.prompt | Full prompt (PII risk) |
| gen_ai.completion | Full completion (PII risk) |

## Project-specific additions (required by our trace contract)
| session_id | Groups spans from one conversation |
| user_id | Who triggered the run |
| prompt_version | Which prompt template version |
| environment | dev / staging / prod |
| cost_usd | tokens x price |
