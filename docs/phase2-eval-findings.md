# Phase 2, Step 18 — Trace Review Findings

Ran 2 of the 25 dataset prompts (rc-001: SMRs, rc-002: quantum computing)
through the agent with Langfuse tracing enabled, and manually reviewed both
traces in the Langfuse UI. Stopped at 2 (not 10) after noticing a large,
unexplained token/cost jump between the two runs — worth documenting as a
finding in its own right, and worth being cautious about cost before
running the remaining 8 later.

## Finding 1: Token cost scales with delegation depth, not tool-call count

Both runs made exactly 3 web_search calls — yet rc-002 used 2.5x more
tokens than rc-001 (478,867 vs 193,565) and took 5x longer (27m32s vs
5m25s). Since the search-call count was identical, the token blow-up isn't
caused by search activity itself.

Root cause: every LLM call in the delegation chain (lead agent -> researcher
-> lead agent -> writer -> lead agent) re-sends the ENTIRE accumulated
conversation history as input — standard LLM API behavior, but it means
cost compounds with each hop, not just with each tool call.

Implication for later phases: Phase 5's cost dashboard should track cost
per delegation hop, not just per run.

## Finding 2: main_agent.py's system prompt references a tool it doesn't have

Both traces end with the model explaining, in its final answer, that
finalize_report "was not actually available in my toolset" — this happens
every time main_agent.py (not checkpointed_agent.py) is used, because
LEAD_AGENT_SYSTEM_PROMPT tells the agent to call finalize_report, but
main_agent.py never registers that tool. Not a crash, but wasted
reasoning/tokens on every run.

Fix to consider before Phase 6: give main_agent.py a separate system
prompt without the finalize_report instruction, or standardize eval runs
on checkpointed_agent.py instead.

## Finding 3: web_search failures are visible but not distinguished from cost/success in the trace summary

In an earlier single run, web_search failed all 3 retry attempts for one
query and returned a descriptive error string instead of crashing — as
designed. But nothing in the current setup flags "tool succeeded but
returned a failure message" differently from "tool succeeded with a real
result" — both look like a normal successful span, since no exception was
raised.

Implication for later phases: Phase 6's trajectory scorers should check
tool output content for known failure-string patterns, not just whether
the call completed without an exception.

## Decision: eval batch paused at 2/10

Given Finding 1 and the project's limited DeepSeek credit budget, the
remaining 8 dataset prompts were deliberately NOT run in this session.
Resume with:

    uv run python -m research_copilot.agents.run_eval_batch --start 2 --limit 8

once credit budget is confirmed comfortable.
