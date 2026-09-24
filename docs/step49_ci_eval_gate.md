# Step 49: PR eval gate (GitHub Actions)

Required: run evals on every PR, and fail the PR if the average score drops
below a threshold.

The Phase 8 plan file (the "plan Qn" references in the code comments) was
never committed and was lost in a Codespace restart. The decisions below are
rebuilt from those comments and the commit messages.

## What was built

`.github/workflows/eval-gate.yml`, which runs on PRs into `develop` and `main`
(plus `workflow_dispatch` once the file is on `main`, Q4):

| Job | What it does | Cost |
|---|---|---|
| `smoke` | `compileall`, `pytest tests/`, then one real graph run on the stub model (`MODEL_PROFILE=stub`) | $0, no secrets |
| `capture` | Matrix over rc-001..rc-003 (Q3). Each prompt runs through the real agent on DeepSeek in parallel, one JSONL row per prompt, uploaded as an artifact | ~$0.08-0.29 per prompt |
| `eval-gate` | Downloads the rows, scores correctness with Step 39's GEval metric (Groq judge, sequential for the 8000 TPM cap), writes the verdict to the job summary | Groq free tier |

The logic lives in `src/research_copilot/evals/ci_gate.py`, and the verdict
rules are unit-tested in `tests/test_ci_gate.py`:

An unscored row could have scored anywhere from 0 to 1, so the gate works
out the worst-case mean (unscored = 0) and the best-case mean (unscored = 1):

- **pass**: worst-case mean >= threshold.
- **fail**: best-case mean < threshold, a run crashed with a code error, or a
  run went past its $1.00 budget (Step 42's max was $0.57, so a bigger bill
  means a loop).
- **inconclusive** (exit 0 plus a warning, Q1/Q2/Q9): a row couldn't be
  scored for a reason outside the PR, **and** its score could still flip
  the verdict. The reasons are: every `web_search` failed (the DuckDuckGo
  block on cloud IPs), a provider or network error, a judge error after
  retries, or a missing row.

A blocked search never fails a PR on its own. With threshold 0.6:

| Rows | Verdict |
|---|---|
| blocked, 1.00, 1.00 | pass (worst case 0.67) |
| blocked, 1.00, 0.00 | inconclusive (0.33-0.67) |
| blocked, 0.00, 0.00 | **fail** (best case 0.33) |
| all 3 blocked | inconclusive |

Before the bounds check (found while reviewing the threshold), the third
row came out inconclusive with exit 0. A real regression could hide behind
one blocked search and still get a green check.

A **partial** block (some searches fail, at least one works) is still
scored. The run has real search results, and nothing reliably tells a
thin-but-honest report from a regression. The 0.6 threshold absorbs one
such prompt; two at once would fail the PR. That residual risk is accepted.

- Fork PRs get no secrets, so `capture` is skipped and `eval-gate` reports
  "not run".

## Secrets

`DEEPSEEK_API_KEY` (capture) and `GROQ_API_KEY` (eval-gate) are read from
repository Actions secrets. Each job's first step fails with a clear error
if its key is empty. In run
[36001831742](https://github.com/SalmaML56/research-copilot-observability/actions/runs/36001831742),
all four secret checks passed: the keys show masked as `***` in the step
env, and the DeepSeek and Groq calls that followed succeeded. Langfuse is
switched off in CI (`LANGFUSE_TRACING_ENABLED=false`), so `prompt_version`
is stamped `local-<hash>`.

## Real CI runs and what they found

1. **Run 36001709064 failed in 10s**, before any code ran:
   `Unable to resolve action astral-sh/setup-uv@v10, unable to find version v10`.
   setup-uv publishes no floating major tag, so it's now pinned to `v10.2.0`
   (commit c6f5716).
2. **Run 36001831742 went green, but the result was wrong.** It showed mean
   0.33 (rc-001 0.00, rc-002 **1.00**, rc-003 0.00). All three answers were
   "research could not be completed" reports. rc-002 got 1.00 because its
   failure report names qubits, IBM, Google and IonQ while describing what
   it had tried, and the GEval judge counted those keywords as the expected
   facts. Step 38's rc-002 "pass" turned out to be the same kind of false
   positive.
   - **Fix:** `ci_gate.no_notes_reason()`. If `write_file` never executed,
     no research notes reached the report, so the row scores 0 without
     asking the judge. Re-scoring that run's real artifacts gives 0.00 on
     all three.
   - The underlying agent bug, why `write_file` never runs, is covered in
     `docs/step51_bad_trace_runbook.md`.
3. Each capture hit a few `web_search exhausted retries` lines on GitHub's
   runners, but 54-167 searches per run succeeded, so no row was
   inconclusive.

## Threshold

The gate was merged report-only (threshold 0.0) because the threshold
should be the baseline minus a margin, and the baseline had to be measured
on GitHub's runners.

| Run | Code | rc-001 | rc-002 | rc-003 | Mean | Cost | Slowest |
|---|---|---|---|---|---|---|---|
| 36001831742 | before Step 51 fixes | 0.00 | 1.00 (false positive) | 0.00 | 0.33 reported, **0.00** honest | $0.46 | 1,641s |
| [36010057083](https://github.com/SalmaML56/research-copilot-observability/actions/runs/36010057083) | after (a893a5f, 5c3e077) | 1.00 | 1.00 | 1.00 | **1.00** | $0.21 | 182s |

In 36010057083, every row passed the no-notes precheck (`write_file` ran)
and every judge reason lists all three expected facts.

**Threshold: 0.6.** With 3 prompts and scores of 0 or 1, the mean can only
be 0, 0.33, 0.67 or 1. So 0.6 lets one flaky prompt through and fails the
PR when two of three break. The baseline is one post-fix run; revisit the
threshold if the gate flakes. The pre-fix code would have failed this gate
(0.00 honest).

## Not done here: branch protection (Q10)

A red check blocks a merge only if `eval-gate` and `smoke` are **required
status checks** in `develop`'s branch protection. That is a repo setting
this token can't read or write (`GET .../branches/develop/protection` →
HTTP 403), so the repo owner has to set it in Settings → Branches.
