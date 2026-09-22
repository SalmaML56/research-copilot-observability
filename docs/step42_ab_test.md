# Step 42 — A/B Test: Frontier (DeepSeek) vs. Open-Weight (Groq) — Findings

Per the Phase 6 plan, ran the same 5 dataset prompts (rc-001–rc-005, the
same scope Steps 38/39 used) through two independent agent instances built
from the identical subagents/tools/middleware/system prompt
(`capture_ab_runs.py`), differing only in the model:

- **primary** — `deepseek-chat` (DeepSeek) via `settings.get_primary_model()`
- **cheap** — `openai/gpt-oss-20b` (Groq) via `settings.get_cheap_model()`

Cost was computed locally per call (`TokenCostCollector`, priced with Step
34's exact rate table) rather than read off a span, because these captures
never call `setup_otel_instrumentation()`. Quality was scored with
`score_ab_runs.py`, reusing Step 39's exact `correctness` (GEval vs.
`expected_facts`) and `faithfulness` (vs. captured `retrieval_context`)
metrics and judge (`GroqJudge`, `openai/gpt-oss-120b`), so cost and quality
sit on the same scale as Steps 38/39.

**Judge-neutrality caveat**, stated up front rather than buried: the judge
shares a provider and model family with the cheap arm's model. Using a
different judge per arm would trade this confound for a worse one (the
judge itself becoming a second independent variable), so both arms are
judged identically — see `capture_ab_runs.py`'s and `score_ab_runs.py`'s
docstrings for the full discussion.

## Results (10/10 pairs attempted, 5/5 primary succeeded, 0/5 cheap succeeded)

| Prompt | primary status | primary cost | primary correctness | primary faithfulness | cheap status | cheap error |
|---|---|---|---|---|---|---|
| rc-001 | ok | $0.036815 | 0.30 (fail) | 1.00 | error (2 attempts) | 413 too large, then 400 tool-call parse |
| rc-002 | ok | $0.083765 | 0.70 (pass) | 1.00 | error | 413 request too large |
| rc-003 | ok | $0.157239 | 1.00 (pass) | 0.95 | error | 429 rate limit |
| rc-004 | ok | $0.253497 | 0.00 (fail) | 1.00 | error | 429 rate limit |
| rc-005 | ok | $0.572479 | 0.30 (fail) | 1.00 | error | 429 rate limit |

Aggregates (`compare_ab_runs.py`, real output):

- **primary**: 5/5 completed. mean cost $0.220759/run (total $1.103795),
  mean elapsed 822.8s (max 1745.1s), mean correctness 0.46 (2/5 pass), mean
  faithfulness 0.99.
- **cheap**: 0/5 completed. Error breakdown (latest attempt per prompt,
  exact `compare_ab_runs.py` output): `{'Error code: 400': 1, 'Error code:
  413': 1, 'Error code: 429': 3}`. rc-001 shows as `400` here because it was
  retried once by the resumed capture run after its first attempt hit `413`
  — both attempts are in the raw `step42_ab_runs.jsonl` (6 rows total for
  the cheap arm across 5 prompts), but the comparison keeps only the latest
  per id, same dedup rule `score_ab_runs.py` already uses.
  No cost or quality numbers exist for this arm — nothing to average.

---

## Finding — the cheap arm cannot complete this workload under Groq's on-demand tier limits

**This is the headline result of Step 42, not a footnote.** The A/B test
was designed to compare cost and quality between a frontier and an
open-weight model. It cannot do that, because the open-weight arm never
produced a single scorable answer. The intended comparison IS the finding:
under this agent's actual token volume, the cheap arm's cost advantage
(Groq's own posted per-token price is ~3x cheaper than DeepSeek's here) is
moot, because the requests it would need to place don't fit Groq's rate
limits in the first place.

**Evidence — error codes, verbatim from `step42_ab_runs.jsonl`:**

- `413`, rc-001: *"Request too large for model `openai/gpt-oss-20b`...
  tokens per minute (TPM): Limit 8000, Requested 8164"*. rc-002: same
  message, *"Requested 8587"*. A single request already exceeds Groq's
  8000 TPM on-demand ceiling for this model — the *same* ceiling Step 39's
  `docs/step38_39_findings.md` already documented for the judge model on
  this org.
- `429`, rc-003/004/005 — a **different, more severe** limit than expected:
  not the per-minute (TPM) ceiling, but a **daily** one — *"Rate limit
  reached... tokens per day (TPD): Limit 200000, Used 198204, Requested
  5234... try again in 24m45s"* (rc-003), climbing to *"Used 199891...
  Requested 3944"* (rc-004) and *"Used 200000... Requested 3990"* (rc-005).
  This message is scoped to `openai/gpt-oss-20b` specifically (the limit
  line names that model), so `GroqJudge` (a different model,
  `openai/gpt-oss-120b`, used for scoring both arms) is not the cause —
  the 20b model's own 200k/day budget was used up by this arm's own prior
  attempts: rc-001's first try alone ran 788s and rc-002's 335s before
  either finally hit the TPM wall, and real tokens are consumed by every
  turn up to that point, not just the one that gets rejected. By rc-003,
  the daily budget was already at 198204/200000 before that run even
  started.

**Root cause, not investigated further (out of scope for Phase 6):**
`build_agent()`'s `SummarizationMiddleware` triggers at 30,000 tokens —
sized for DeepSeek, which has no comparably tight ceiling on this plan.
Groq's on-demand tier caps `openai/gpt-oss-20b` at 8000 TPM *and* 200,000
TPD, so a research agent's tool-heavy, multi-call conversation both
(a) routinely exceeds the per-request 8000 TPM ceiling before 30,000
tokens accumulate, and (b) burns through the 200k daily budget within a
handful of attempts even when a given request stays under the TPM
ceiling. Lowering the summarization trigger for the cheap arm
specifically, or moving to a paid Groq tier, would be the two obvious
follow-ups — neither attempted here, since changing the agent's config
specifically to make one A/B arm pass would undermine the A/B comparison
itself (Steps 38–41's `main_agent.py` config stays the single source of
truth both arms build from).

**Why the retry-and-resume in `capture_ab_runs.py` didn't help:** it
resumes based on `status: "ok"` rows already in the output file, which is
correct behavior — but every cheap-arm attempt failed, so every one of
them was retried on the next invocation and failed again the same way
(rc-001-cheap: 413 on the first pass, then a different failure, `400`
tool-call-argument parse error, on the retry — itself plausibly a symptom
of the same token-budget pressure corrupting a truncated tool call, not
investigated further).

## Verification

- All 5 primary-arm rows confirmed scored: `step42_scores.jsonl` has 5
  rows, one per `*-primary` id, each with both `correctness_score` and
  `faithfulness_score`.
- Scores confirmed actually reaching Langfuse, not just written locally:
  queried the `scores` table directly in the `langfuse-clickhouse`
  container for all 5 primary trace IDs (the REST `/api/public/scores`
  endpoint 404s on this self-hosted v4 "events_only" deployment, the same
  constraint already documented in Step 40's write-up) — all 10 rows
  (5 traces × 2 metrics) present with matching values.
- `compare_ab_runs.py` run against the real files, output pasted above
  verbatim (not summarized/rounded by hand).

## Files involved

- `src/research_copilot/evals/capture_ab_runs.py` — this step
- `src/research_copilot/evals/score_ab_runs.py` — this step
- `src/research_copilot/evals/compare_ab_runs.py` — this step
- `data/eval_results/step42_ab_runs.jsonl`, `data/eval_results/step42_scores.jsonl`
  — captured/scored data for rc-001–rc-005 (gitignored, same as Steps 38–40)
