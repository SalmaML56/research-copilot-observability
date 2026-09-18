# Step 18 — Dataset Prompt Run & Findings

Per the review action plan: run all 10 dataset prompts, read the traces, write 3
findings with evidence (prompt ID, model/config, trace/session ID, outcome,
anything unexpected). Only claims backed by a real run and real evidence are
recorded here.

## Prompt Results (10/10)

| ID | Topic | Outcome | Notes |
|---|---|---|---|
| rc-001 | Small modular nuclear reactors | Completed | From earlier session (pre-review) |
| rc-002 | Quantum computing | Completed | From earlier session (pre-review) |
| rc-003 | 2008 financial crisis | Completed | Paused for approval, then completed normally |
| rc-004 | CRISPR gene editing | Completed | Paused for approval, then completed normally |
| rc-005 | EV battery technology | Completed | Completed directly, no approval pause |
| rc-006 | Fall of the Roman Empire | Completed | Paused for approval, then completed normally |
| rc-007 | CAP theorem | Completed | Paused for approval, then completed normally |
| rc-008 | Intermittent fasting health effects | Completed (after fix) | Hung indefinitely before fix — see Finding 1 |
| rc-009 | Fusion energy research | Completed (after fix) | Hung indefinitely before fix, repeatedly — see Finding 1 |
| rc-010 | General relativity | Completed | Self-corrected mid-run — see Finding 3 |

All 10 prompts now complete. rc-008 and rc-009 required a code fix during this
run (Finding 1) before they would complete at all.

---

## Finding 1 — LLM and web search calls had no timeout, causing indefinite hangs

**Prompts affected:** rc-008, rc-009 (both reproduced the hang on repeated,
independent attempts with fresh server state — not a one-off fluke).

**Evidence:** Used `py-spy dump` against the live server process while a hung
request was in progress (not guessed from logs). Two separate root causes were
found this way:

1. `ChatDeepSeek`/`ChatGroq` were instantiated in
   `src/research_copilot/config/settings.py` with no `timeout` parameter. A
   py-spy dump during a hang showed a thread parked in `ssl.py:1180` inside
   the DeepSeek client call chain, with no time bound — confirmed by running
   the model directly outside the agent (succeeded in 5.4s), proving the
   model itself wasn't slow; the missing timeout was the bug.
2. After fixing (1), rc-009 still hung. A second py-spy dump showed a
   *different* thread stuck the same way, this time inside
   `DDGS().text()` (the web search tool). DDGS advertises a 5-second default
   timeout, but it was not reliably honored in this network environment —
   the call blocked for 5+ minutes with no exception raised.

**Fix:** `timeout=90, max_retries=2` added to both chat models. `web_search`
now runs inside a dedicated thread pool with `future.result(timeout=8)` as a
hard wall-clock bound independent of DDGS's own timeout handling; retries
reduced from 3 to 2 attempts.

**Verification:** Re-ran rc-009 from a clean server restart after each fix.
Confirmed via `py-spy` that no thread remained parked indefinitely after the
fix, and via direct checkpoint-state inspection
(`agent.get_state(config)`) that the run progressed and eventually completed,
rather than being silently declared done.

**Residual behavior (documented, not hidden):** Even with both timeouts in
place, rc-009 could still take several minutes end-to-end on a run where most
individual search attempts fail and get retried — this is bounded now
(will always finish or error within a predictable window) but not fast. See
Finding 2.

---

## Finding 2 — Search-engine reachability from this environment is unreliable (infrastructure, not application code)

**Prompts affected:** rc-008, rc-009 primarily; likely any prompt is equally
exposed depending on timing.

**Evidence:** The application's own existing fallback message (written before
this session) already anticipated this: `web_search`'s failure path returns
*"This is often a temporary block on cloud IPs."* During live debugging,
`py-spy` repeatedly showed search threads blocked mid-HTTP-request
(`ddgs/http_client.py`) against multiple different backend engines (DuckDuckGo,
Startpage), with `ss -tnp` separately showing several `CLOSE-WAIT` sockets to
external hosts that never cleanly closed.

**Interpretation:** `ddgs` rotates across several underlying search engines.
Cloud-hosted IPs (this Codespace included) are sometimes rate-limited or
temporarily blocked by these engines because automated traffic commonly
originates from cloud IP ranges. This is not specific to the fasting or
fusion-energy topics — no topic-level pattern was found, and the failure
looked like it depended on which backend engine got selected and its
block status at that moment, not on the query content.

**Action:** No further code fix is applicable here — network/IP reliability
to third-party search engines is outside this application's control. Finding
1's timeout work ensures this condition now degrades gracefully (bounded
retry + clear error) instead of hanging the whole request indefinitely.

---

## Finding 3 — Lead agent's file-verification self-correction has no retry cap (partially addressed)

**Prompt:** rc-010 (and observed again mid-investigation on rc-009's second
hang before the timeout fix landed).

**Evidence:** `rc-010`'s final response included this from the lead agent
itself:

> "One initial research attempt claimed success but had not actually created
> the notes file (confirmed by a real read error); this was re-delegated and
> verified before writing."

This confirms the `LEAD_AGENT_SYSTEM_PROMPT` instruction *"do not redo its
work ... unless you explicitly try read_file and get a real error"* is
working as intended — the lead agent does not blindly trust a subagent's
claim, and checks the filesystem before accepting a handoff. On rc-010 this
resolved correctly on the first retry.

However, while investigating rc-009's hang, checkpoint state
(`agent.get_state(config).values["messages"]`) showed the *same* pattern
triggering repeatedly, with the prompt providing no upper bound on how many
times the lead agent could relaunch the researcher subagent if the file kept
appearing missing.

**Fix:** `LEAD_AGENT_SYSTEM_PROMPT` updated to cap this at one relaunch (two
attempts total). If the notes file is still missing after that, the agent is
instructed to call `finalize_report` with a short explanation rather than
retrying again.

**Not yet independently verified:** this specific cap was not exercised by a
live run that actually hit the missing-file condition twice in a row after
the fix landed (Finding 1's timeout fix changed the failure mode before this
could be observed again under controlled conditions). Recorded as a
code-level fix backed by the same evidence that motivated it, not as a
freshly re-confirmed behavior — flagged here rather than claimed as fully
tested, consistent with the standard this review holds every other item to.

---

## Files changed (Step 18 follow-up fixes)

- `src/research_copilot/config/settings.py` — model timeouts
- `src/research_copilot/agents/tools.py` — hard search timeout
- `src/research_copilot/agents/subagents.py` — capped self-correction retries
