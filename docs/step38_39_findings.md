# Step 38/39 — Offline Eval Capture & Scoring: Findings

Per the Phase 6 plan, captured and scored 5 dataset prompts (rc-001–rc-005 —
enough to demonstrate the framework, not the full 25-prompt dataset) through
the full offline eval pipeline: `capture_runs.py` runs each prompt through
the live agent and saves answer/retrieval_context/tool_calls/trace_id to
`data/eval_results/step38_runs.jsonl`; `score_runs.py` scores each row with
DeepEval (judge: `openai/gpt-oss-120b` on Groq, see `judge.py`) on two
metrics and writes scores back onto the matching Langfuse trace.

- **correctness** — `GEval`, answer vs. `expected_facts` (no reference
  answer exists, only a fact checklist, so this is a criteria-based metric
  rather than an off-the-shelf one).
- **faithfulness** — DeepEval's `FaithfulnessMetric`, answer vs.
  `retrieval_context` (the captured `web_search` outputs). Catches claims
  not supported by the search results actually returned.

Threshold 0.5 on both (DeepEval's default), descriptive only — a failing
score is reported, not enforced; gating is out of scope for Phase 6.

## Results (5/5 captured, 5/5 scored)

| ID | Capture status | Correctness | Faithfulness | Trace ID |
|---|---|---|---|---|
| rc-001 | ok | **fail (0.00)** | pass (1.00) | `524a3704...` |
| rc-002 | ok | pass (1.00) | pass (1.00) | `ac479320...` |
| rc-003 | ok | **fail (0.00)** | pass (1.00) | `057c5e4a...` |
| rc-004 | ok | pass (1.00) | pass (1.00) | `93560812...` |
| rc-005 | ok | **fail (0.00)** | pass (1.00) | `7bcd8f45...` |

All 5 rows have capture `status: "ok"` — `capture_runs.py` raised no
exception on any of them. The correctness scores tell a different story.

---

## Finding — `status: "ok"` does not mean the agent answered the question

**Prompts affected:** rc-001, rc-003, rc-005 (3 of 5 — 60% of this sample).

**Evidence:** All three answers are the lead agent explicitly reporting it
could not complete the research, not a substantive response. From the
captured `answer` field:

> rc-001: "Research could not be completed, so no substantive report on
> SMRs was produced... The researcher reported it was writing the notes,
> but verification via `read_file` returned 'file not found,' and
> `glob`/`ls` showed no files in the working filesystem at all."

> rc-003: "Research could not be completed for this topic. I delegated the
> research task twice to the researcher subagent... no notes file was ever
> produced — direct reads of that path returned 'file not found'..."

> rc-005: "The research task could not be completed, and I've finalized a
> report documenting that outcome... First research attempt..." (same
> write/read mismatch pattern)

The judge's `correctness_reason` for each independently confirms this is a
real gap, not a scoring artifact: e.g. rc-001 — *"contains no mention of
any of the three expected facts... it only describes a failed research
process, so it does not align with the expected output at all."*

**This is the known failure mode from Step 18 Finding 3, bounded but not
fixed.** `LEAD_AGENT_SYSTEM_PROMPT`
(`src/research_copilot/agents/subagents.py:46`) already caps this: if
`read_file` confirms the researcher's notes file is genuinely missing, the
lead agent may relaunch the researcher subagent **at most once more**, then
must call `finalize_report` with a short "could not complete" explanation
instead of retrying indefinitely. That cap is working exactly as designed
here — no hang, no infinite loop, a clean terminal response. But the
underlying question Step 18 left open is still open: **why does the
researcher's `write_file` report success while the lead agent's
`read_file`/`glob` on the identical path finds nothing, in 3 of 5 runs?**

Candidates, not investigated (out of scope for Phase 6, per explicit
scope decision):
- `deepagents.FilesystemMiddleware` is instantiated separately per subagent
  (`subagents.py:18` for the researcher, `:36` for the writer/lead read
  path) — worth checking whether each instance holds independent virtual-FS
  state rather than a filesystem shared through the graph's checkpointed
  state.
- A race between the researcher's write and the lead agent's read.
- Something specific to this Codespace's filesystem/session handling.

**Why this matters, and why it's the headline result of Steps 38/39 rather
than a footnote:** faithfulness stayed at a clean 1.00 across all 5 rows,
including the 3 failures — a "the research could not be completed" answer
doesn't hallucinate against irrelevant context, it just isn't useful.
Correctness-against-expected-facts is what surfaced a 60% real task-failure
rate that was otherwise completely hidden behind uniform "success" at the
capture layer. This is exactly the class of gap an eval framework exists to
catch, and Steps 38/39 caught it on the very first 5-prompt run.

**Action:** Documented here as a known issue for future work. Not
investigated or fixed in Phase 6 — flagged for Phase 7 or a dedicated
follow-up to trace `FilesystemMiddleware` state sharing between subagents.

---

## Also observed — Groq free-tier rate limits shape what the judge can see

Not a bug, but relevant to Step 40 (online evals, same `GroqJudge`) and
worth recording alongside the finding above: the Groq on-demand tier caps
`openai/gpt-oss-120b` at 8000 tokens/minute. Raw `retrieval_context` per row
ran 19k–23k tokens (measured directly against this dataset) and one row's
answer (rc-004, 12,533 chars vs. ~1,000-1,700 for every other row) produced
a claims list large enough to break the faithfulness judge's structured
JSON output at `max_tokens=4096`. `score_runs.py` now caps context/answer
text fed to the judge and retries rate-limit/transient errors with
backoff — see the inline comments in `score_runs.py` for the exact budgets
and the live error evidence that motivated each one. This means the
faithfulness judge is scoring against a truncated view of long
answers/contexts, a real tradeoff against the 8000 TPM ceiling, not a
free correctness improvement.

## Files involved

- `src/research_copilot/evals/capture_runs.py` — Step 38 (already
  committed)
- `src/research_copilot/evals/judge.py` — Step 38 (already committed)
- `src/research_copilot/evals/score_runs.py` — Step 39 (this step)
- `data/eval_results/step38_runs.jsonl`, `data/eval_results/step39_scores.jsonl`
  — captured/scored data for rc-001–rc-005
- `src/research_copilot/agents/subagents.py` — unmodified this step; the
  relevant retry cap (Step 18 Finding 3) lives at line 46
