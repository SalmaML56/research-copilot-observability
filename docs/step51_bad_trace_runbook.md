# Runbook: diagnosing and fixing a bad trace

Step 51. One page, from "this answer is bad" to "fixed and proven". The
worked example is a real failure: 3 of 5 Step 38 runs and 3 of 3 runs in
the first CI eval gate.

## 1. Detect: which signal fired?

| Signal | Where | What it means |
|---|---|---|
| Eval gate red, or correctness 0 | PR check `eval-gate`, job summary table | Answer is missing the expected facts |
| `write_file never ran` in the judge reasons | same table | The research never reached the report (step 4) |
| `status=error` / inconclusive | gate summary, "Not scored" list | Crash, provider outage, or blocked search. **Not** an answer-quality problem |
| Low online-eval score / thumbs down | Langfuse scores (Steps 40, 43) | A production trace to pull |
| Error or slow span | Grafana Tempo (Step 32 session search) | Tail sampling keeps every error trace (Step 44) |

**Do not trust `status: ok`.** It only means nothing raised. All three
failed Step 38 runs were `ok`.

## 2. Locate the trace

- Eval rows (`data/eval_results/*.jsonl`, CI artifact `runs-<id>`) carry
  `trace_id` and `prompt_version`. CI runs with Langfuse off, so re-run the
  prompt locally to get a trace:
  `uv run python -m research_copilot.evals.ci_gate capture --id rc-001 --out-dir runs/`
- API requests: search Tempo/Langfuse by `session.id`. `prompt_version`
  tells you which prompt text ran (Step 50). `local-<hash>` means the text
  was not synced to Langfuse.

## 3. Read the trace

```
uv run python scripts/phase8/inspect_trace.py <trace_id>
```

It prints the tools that executed, the **invalid tool calls** (emitted by
the model but unparseable, so never run), and what each subagent handed
back. Two traps:

- This self-hosted Langfuse runs v4 `events_only`, so
  `GET /api/public/traces/<id>` returns "not available". The script uses
  `/api/public/v2/observations`.
- A missing span is not evidence the model didn't try. An `invalid_tool_call`
  never becomes a TOOL span, so check generation outputs too.

## 4. Find the root cause: prove it, don't theorize

Worked example, trace `524a3704…` (Step 38 rc-001):

1. **Symptom.** The lead's `read_file` on the notes path says "file not
   found". The researcher returned *"I now have comprehensive material. Let
   me write the notes file."*
2. **Theories ruled out by the trace.** Per-subagent `FilesystemMiddleware`
   state and a write/read race, both listed in `step38_39_findings.md`, need
   a `write_file` that ran. There were **zero** `write_file` spans.
3. **The actual cause.** Both researcher attempts end in an
   `invalid_tool_call` for `write_file`: ~14.8k chars of args,
   `Unterminated string`. The JSON was cut off mid-string. An AIMessage with
   no *valid* tool call ends the subagent loop, so the "let me write…" text
   became the handoff.
4. **Confirmed on every trace.** In all 6 Step 38 traces, every failed
   handoff is a truncated `write_file` (14.8k-16.6k chars). The only
   successful write in rc-004 was 15.6k chars, just under the limit.
5. **Reproduced in isolation.** Same model and `MAX_TOKENS=4096`, same
   search context, researcher prompt: `finish_reason: length`,
   `output_tokens: 4096`, `write_file` args 15,110 chars in
   `invalid_tool_calls`.

**Root cause:** the researcher writes all its notes in one `write_file`
call. Past ~4096 output tokens the call is truncated, becomes unparseable,
and is silently dropped.

## 5. Fix at the narrowest layer, then version it

- **Agent:** the researcher and writer prompts (`agents/subagents.py`)
  cap notes and report at ~800 words, and tell the model why. The writer
  cap is needed because the lead re-emits the whole report as
  `finalize_report`'s argument. That call failed the same way once the
  handoff worked (18,271 chars, truncated). On the same repro:
  `finish_reason: tool_calls`, 1,856 output tokens, a valid 6.5k-char
  `write_file`. Raising `MAX_TOKENS` was not chosen: the notes had no upper
  bound, so it moves the cliff instead of removing it. And a 4k-token call
  already takes ~80s against the 90s LLM timeout.
- **Gate:** the judge scored two failure reports 1.00, because they list
  the expected keywords while explaining what was attempted. Rows where
  `write_file` never executed now score 0 without the judge
  (`ci_gate.no_notes_reason`).
- **Gate crash:** `capture_runs` recorded that empty final answer as `ok`,
  which crashed `ci_gate score`. Step 42 had already fixed this, but only in
  `capture_ab_runs`. It is now `EmptyFinalAnswer`, which fails the gate.
- **Version:** `uv run python scripts/phase8/sync_prompts.py` created
  researcher v2 and writer v2 (`--check` exits 0). Traces are now stamped
  `lead=1,researcher=2,writer=2` instead of `...=1`, so before and after can
  be told apart.

## 6. Verify end to end

Re-run the same prompt through the real agent (DeepSeek) and read the new
trace with the same script:

| rc-001 | Trace | Invalid calls | `write_file` | `finalize_report` | Correctness |
|---|---|---|---|---|---|
| Before (Step 38) | `524a3704…` | 2 × `write_file` | never ran | "could not complete" | 0.00 |
| Researcher cap only | `9b398142…` | 1 × `finalize_report` (18.3k chars) | ran (1) | never ran, empty answer | crashed the scorer |
| Both caps | `0a5180c7…` | none | ran, 7.8k chars | ran, 9.7k chars | **1.00**, all 3 facts |

rc-003 with the researcher cap: `write_file` ran on the first attempt, the
writer was delegated, and a real report came out (82s/$0.04, against
166s/$0.08 for the failed CI run). rc-002 and rc-003 with both caps also
completed the handoff (no invalid calls). The gate marked them
inconclusive because DuckDuckGo blocked every search from the Codespace
at the time. The gate is right not to score a report built without
search results. The full 3-prompt check runs in CI (`docs/step49_ci_eval_gate.md`).

**Trap found while verifying:** local `ci_gate capture` runs all used the
label `ci-local-1`. Trace ids are seeded from it, so a re-run appended to
the previous run's trace (453 observations, both runs mixed). Local labels
now include a timestamp.

## Checklist

- [ ] Signal identified, and not an infra/inconclusive case
- [ ] Trace pulled, and `inspect_trace.py` output read (tools, invalid calls, handoffs)
- [ ] Cause proven with a repro, not a theory that fits
- [ ] Fix at the narrowest layer, plus a unit test or gate check
- [ ] Prompt synced (`sync_prompts.py --check` exits 0), new `prompt_version` on traces
- [ ] Same prompt re-run: new trace shows the fixed behaviour, and correctness is scored
- [ ] Findings doc updated, one commit per verified change
