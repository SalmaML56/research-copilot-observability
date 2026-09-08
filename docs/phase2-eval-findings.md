# Phase 2, Step 18 — Trace Review Findings (Expanded)

Ran 2 of the 25 dataset prompts (rc-001: SMRs, rc-002: quantum computing)
through the agent with Langfuse tracing enabled, and manually reviewed both
traces in the Langfuse UI. Stopped at 2 (not 10) after noticing a large,
unexplained token/cost jump between the two runs.

---

## Finding 1: Token cost scales with delegation depth, not tool-call count

**What we observed:** Both runs made exactly 3 web_search calls — the
exact same number. Yet rc-002 (quantum computing) used 2.5x more tokens
than rc-001 (SMRs): 478,867 vs 193,565 tokens, and took 5x longer
(27m32s vs 5m25s).

**Why this happens:** LLM APIs have no built-in "memory" between calls.
Every single LLM call in this project's delegation chain — lead agent
plans, researcher searches, researcher reports back to lead agent, lead
agent delegates to writer, writer reads notes and responds, lead agent
finalizes — has to re-send the ENTIRE conversation so far as input, every
single time. Think of it like re-reading an entire book from page one
every time you want to add one more sentence to it, instead of just
remembering what you already read.

So the cost isn't driven by "how many searches did we do" — it's driven by
"how many back-and-forth steps did the agent take, and how much text
accumulated in the conversation along the way." A topic where the
researcher wrote longer notes, or the writer produced a longer report,
costs more — even with identical tool usage — simply because more text
gets re-transmitted at every subsequent step.

**Real-world analogy:** Imagine a group project where every time someone
adds a paragraph, the whole document gets re-emailed to everyone from
scratch, in full, so they have the full context. Five short paragraphs
mean five short emails. But if one of those paragraphs happens to be a
full page, every email after that point is now a page long — the number
of emails (steps) didn't change, but the total data sent did.

**What this means going forward (Phase 5, cost dashboards):** We can't
just track "cost per run" — we need to track cost per delegation hop, so
we can spot which step in the chain is driving the expense.

---

## Finding 2: main_agent.py's system prompt referenced a tool it didn't have (NOW FIXED)

**What we observed:** Every trace ended with the model apologizing that
"the finalize_report tool referenced in my instructions was not actually
available in my toolset" — and then delivering the report directly
instead.

**Why this happened:** LEAD_AGENT_SYSTEM_PROMPT (shared by all agent
variants) tells the lead agent to call finalize_report as its last step.
But main_agent.py — the simple, non-persistent version built for Steps
6-8 — never actually registered that tool when the agent was built.

**Was this a crash or data-loss bug?** No — the agent recovered
gracefully every time and still delivered a complete, correct report. But
it wasted a small amount of reasoning/tokens each run explaining the
mismatch.

**What we did about it:** Fixed by adding tools=[finalize_report] to
main_agent.py's create_deep_agent(...) call. Re-ran the exact same SMR
task afterward and confirmed: no more apology, todo list shows "Finalize
the report" as completed (previously stuck at in_progress), clean report
output. Verified via a real terminal run.

**Lesson for future agent variants:** When multiple agent files share one
system prompt, double-check every file using that prompt actually has
every tool it references registered.

---

## Finding 3: Failed tool calls look identical to successful ones in the trace UI

**What we observed:** In an earlier single run, web_search failed all 3
of its internal retry attempts for one query (a real network-level
failure, not a bug) and — as designed — returned a descriptive error
string instead of raising an exception and crashing the run.

**The problem:** In the Langfuse trace view, that failed search shows up
with a green "success" status, exactly like every other search that
returned real, useful results. The only way to tell the difference is to
open the span and read the Output text itself.

**Why this matters:** Glancing at a dashboard full of green checkmarks
could hide that some "successful" tool calls actually returned useless
failure messages instead of real data.

**What this means going forward (Phase 6):** Trajectory scorers need to
check the content of tool outputs for known failure-string patterns, not
just whether the call completed without throwing an exception.

---

## Decision: eval batch paused at 2/10

Given Finding 1 and the project's limited DeepSeek credit budget, the
remaining 8 dataset prompts were deliberately NOT run in this session —
a documented choice, not an oversight. Resume with:

    uv run python -m research_copilot.agents.run_eval_batch --start 2 --limit 8

once credit budget is confirmed comfortable.
