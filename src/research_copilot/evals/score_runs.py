"""
Phase 6, Step 39: score the runs captured by capture_runs.py and write the
scores back onto their Langfuse traces.

Two metrics per row, both judged by GroqJudge (see judge.py for why Groq/
gpt-oss-120b instead of DeepEval's OpenAI default):

  correctness   GEval, answer vs. expected_facts. There's no reference
                answer to diff against, only a fact checklist, so this is a
                custom criteria-based metric rather than an off-the-shelf one.
  faithfulness  DeepEval's FaithfulnessMetric, answer vs. retrieval_context
                (the captured web_search outputs). Catches claims the answer
                makes that the search results don't support.

Threshold 0.5 (DeepEval's default) on both. Descriptive only: a failing
score is reported, not enforced - gating is out of scope for this phase.

Run:
    uv run python -m research_copilot.evals.score_runs
"""

import json
import re
import time
from pathlib import Path

from deepeval.metrics import FaithfulnessMetric, GEval
from deepeval.test_case import LLMTestCase, LLMTestCaseParams
from groq import APIStatusError, RateLimitError
from langfuse import get_client

from research_copilot.evals.judge import GroqJudge

RUNS_PATH = "data/eval_results/step38_runs.jsonl"
DEFAULT_OUT = "data/eval_results/step39_scores.jsonl"
THRESHOLD = 0.5

# Groq's on-demand tier caps openai/gpt-oss-120b at 8000 tokens/minute.
# FaithfulnessMetric sends the whole retrieval_context in one prompt to
# extract "truths"; the captured web_search outputs run 19k-23k tokens per
# row (measured directly against this dataset), 2-3x over a single request's
# budget. Capping to a char budget keeps the truths-extraction call well
# under the limit; the correctness/claims/verdicts calls are small (~1-2k
# tokens each) by comparison. CONTEXT_CHAR_BUDGET is a judged tradeoff, not
# a hard constant: kept low enough that budget + those other calls together
# stay inside 8000 TPM, at the cost of dropping later search results if a
# row has many of them (order-preserved, so earlier - typically more
# relevant - results survive).
CONTEXT_CHAR_BUDGET = 12000
# FaithfulnessMetric extracts one "claim" per sentence-ish unit of
# actual_output, then asks the judge to verdict every claim against the
# truths in one JSON array response. rc-004's answer (12,533 chars, 7x any
# other row) produced a verdicts response Groq's API rejected as invalid
# JSON at max_tokens=4096 (three retries, same failure each time - not
# rate-limit flakiness). Capping the answer text fed to the faithfulness
# judge keeps the claims list, and so the verdicts response, bounded. Only
# faithfulness gets this cap: correctness (GEval, single score+reason
# output) handled the full 12,533-char answer without issue.
FAITHFULNESS_ANSWER_CHAR_BUDGET = 4000
ROW_PACING_SECONDS = 20
RATE_LIMIT_RETRY_ATTEMPTS = 3
WAIT_TIME_PATTERN = re.compile(r"try again in ([\d.]+)s")

CORRECTNESS_CRITERIA = (
    "Determine whether 'actual output' states each fact listed in "
    "'expected output', allowing paraphrase and additional detail. Penalize "
    "missing facts and factual contradictions; do not penalize extra "
    "correct information beyond the listed facts."
)


def load_runs(path: str) -> list[dict]:
    """One row per id: later records (retries) win over earlier ones."""
    by_id: dict[str, dict] = {}
    with open(path) as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            by_id[row["id"]] = row
    return [row for row in by_id.values() if row.get("status") == "ok"]


def cap_context(outputs: list[str], char_budget: int) -> list[str]:
    """Keep outputs in order up to char_budget, truncating the one that overflows."""
    capped: list[str] = []
    remaining = char_budget
    for text in outputs:
        text = str(text)
        if remaining <= 0:
            break
        if len(text) > remaining:
            capped.append(text[:remaining])
            break
        capped.append(text)
        remaining -= len(text)
    return capped or [""]


def measure_with_backoff(metric, test_case) -> None:
    """Groq's 8000 TPM cap is tight enough that one row's calls can trip a
    429 mid-run (seen live: 7946/8000 used, next call requested 4037). Groq
    tells us exactly how long to wait, so honor that instead of guessing.
    Also retries other Groq API errors (seen live: a 400 json_validate_failed
    on a row with an unusually long answer, most likely the judge's verdicts
    array getting truncated at max_tokens=4096) - temperature=0 makes this a
    weak fix, but the API isn't fully deterministic in practice either."""
    for attempt in range(1, RATE_LIMIT_RETRY_ATTEMPTS + 1):
        try:
            metric.measure(test_case)
            return
        except APIStatusError as e:
            if attempt == RATE_LIMIT_RETRY_ATTEMPTS:
                raise
            if isinstance(e, RateLimitError):
                match = WAIT_TIME_PATTERN.search(str(e))
                wait = float(match.group(1)) + 2 if match else 30.0
            else:
                wait = 10.0
            print(f"    {type(e).__name__}, waiting {wait:.0f}s (attempt {attempt}/{RATE_LIMIT_RETRY_ATTEMPTS})")
            time.sleep(wait)


def score_row(row: dict, correctness: GEval, faithfulness: FaithfulnessMetric) -> dict:
    correctness_case = LLMTestCase(
        input=row["prompt"],
        actual_output=row["answer"],
        expected_output="\n".join(row["expected_facts"]),
    )
    faithfulness_case = LLMTestCase(
        input=row["prompt"],
        actual_output=row["answer"][:FAITHFULNESS_ANSWER_CHAR_BUDGET],
        retrieval_context=cap_context(row["retrieval_context"], CONTEXT_CHAR_BUDGET),
    )

    measure_with_backoff(correctness, correctness_case)
    measure_with_backoff(faithfulness, faithfulness_case)

    return {
        "id": row["id"],
        "trace_id": row["trace_id"],
        "correctness_score": correctness.score,
        "correctness_passed": correctness.score >= THRESHOLD,
        "correctness_reason": correctness.reason,
        "faithfulness_score": faithfulness.score,
        "faithfulness_passed": faithfulness.score >= THRESHOLD,
        "faithfulness_reason": faithfulness.reason,
    }


def push_to_langfuse(client, result: dict) -> None:
    client.create_score(
        trace_id=result["trace_id"],
        name="correctness",
        value=result["correctness_score"],
        data_type="NUMERIC",
        comment=result["correctness_reason"],
    )
    client.create_score(
        trace_id=result["trace_id"],
        name="faithfulness",
        value=result["faithfulness_score"],
        data_type="NUMERIC",
        comment=result["faithfulness_reason"],
    )


def main() -> None:
    runs = load_runs(RUNS_PATH)
    print(f"{len(runs)} run(s) with status=ok to score\n")

    judge = GroqJudge()
    correctness = GEval(
        name="Correctness",
        criteria=CORRECTNESS_CRITERIA,
        evaluation_params=[LLMTestCaseParams.ACTUAL_OUTPUT, LLMTestCaseParams.EXPECTED_OUTPUT],
        model=judge,
        threshold=THRESHOLD,
    )
    # async_mode=False: truths-extraction and claims-extraction otherwise
    # fire concurrently, doubling the peak simultaneous token spend against
    # the same 8000 TPM budget. Sequential is slower but stays predictable.
    faithfulness = FaithfulnessMetric(model=judge, threshold=THRESHOLD, async_mode=False)

    client = get_client()
    out = Path(DEFAULT_OUT)
    out.parent.mkdir(parents=True, exist_ok=True)

    already_scored: set[str] = set()
    if out.exists():
        with out.open() as f:
            for line in f:
                if line.strip():
                    already_scored.add(json.loads(line)["id"])
    todo = [row for row in runs if row["id"] not in already_scored]
    if already_scored:
        print(f"resuming: {len(already_scored)} already scored, {len(todo)} remaining\n")

    with out.open("a") as f:
        for i, row in enumerate(todo, 1):
            print(f"[{i}/{len(todo)}] {row['id']}")
            result = score_row(row, correctness, faithfulness)
            f.write(json.dumps(result) + "\n")
            f.flush()
            push_to_langfuse(client, result)
            print(
                f"    correctness={result['correctness_score']:.2f} "
                f"({'pass' if result['correctness_passed'] else 'fail'})  "
                f"faithfulness={result['faithfulness_score']:.2f} "
                f"({'pass' if result['faithfulness_passed'] else 'fail'})"
            )
            if i < len(todo):
                time.sleep(ROW_PACING_SECONDS)

    client.flush()
    print(f"\nWrote {out}, pushed scores to Langfuse")


if __name__ == "__main__":
    main()
