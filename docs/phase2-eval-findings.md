# Phase 2, Step 18 — Trace Review Findings (Expanded, with fixes applied)

Ran 2 of the 25 dataset prompts (rc-001: SMRs, rc-002: quantum computing)
through the agent with Langfuse tracing enabled, and manually reviewed both
traces in the Langfuse UI. Stopped at 2 (not 10) after noticing a large,
unexplained token/cost jump between the two runs.

**Final status of all 3 findings: all addressed.**

| Finding | Status |
|---|---|
| 1 — Cost scales with delegation depth | MITIGATED — SummarizationMiddleware added |
| 2 — main_agent.py referenced a missing tool | FIXED |
| 3 — Failed searches looked identical to successful ones | FIXED |

---

## Finding 1: Token cost scales with delegation depth, not tool-call count — MITIGATED

**What we observed:** Both runs made exactly 3 web_search calls — the
exact same number. Yet rc-002 (quantum computing) used 2.5x more tokens
than rc-001 (SMRs): 478,867 vs 193,565 tokens, and took 5x longer
(27m32s vs 5m25s).

**Why this happens:** LLM APIs have no built-in "memory" between calls.
Every LLM call in the delegation chain re-sends the ENTIRE conversation
so far as input, every time.

**Can this be fully "fixed"?** No — it's inherent to how LLM APIs work.
But it CAN be mitigated.

**What we did:** Added SummarizationMiddleware to main_agent.py. Once a
running conversation passes ~30,000 tokens, it automatically compresses
older messages into a summary before the next LLM call, instead of
re-sending the full, ever-growing history every time. The most recent 15
messages are always kept verbatim.

**Verified:** Agent still builds and runs correctly with this middleware
added. Neither of our 2 test runs crossed the 30,000-token trigger on
their own, so we haven't yet observed the trigger actually fire — worth
watching for in future longer runs.

---

## Finding 2: main_agent.py's system prompt referenced a tool it didn't have — FIXED

**What we did:** Added tools=[finalize_report] to main_agent.py's
create_deep_agent(...) call.

**Verified:** Re-ran the same SMR task — confirmed via real terminal
output: no more apology, todo list shows "Finalize the report" as
completed, clean report output.

---

## Finding 3: Failed tool calls looked identical to successful ones in the trace UI — FIXED

**What we did:** Added a call to Langfuse's
get_client().update_current_span(level="WARNING", status_message=...)
inside web_search's failure path.

**Verified:** Built a one-off test script that force-fails web_search and
confirmed the new code path executes without error. A live visual check
of the WARNING color in the Langfuse UI on a genuinely triggered real
failure is still worth doing opportunistically in future runs.

---

## Decision: eval batch paused at 2/10

Given Finding 1 and the project's limited DeepSeek credit budget, the
remaining 8 dataset prompts were deliberately NOT run in this session.
Resume with:

    uv run python -m research_copilot.agents.run_eval_batch --start 2 --limit 8

once credit budget is confirmed comfortable.
