# Trace Contract

Every span in this project MUST carry these five attributes:

| Attribute | Type | Set where |
|---|---|---|
| session_id | string | top of request, propagated to all child spans |
| user_id | string | same |
| prompt_version | string | whichever prompt template produced the LLM call |
| environment | string | dev/staging/prod, from config/settings.py |
| cost_usd | float | computed at span-close: tokens x price |

Enforced structurally (not "remember to add it") via a Collector processor
added in Phase 3, step 23.
