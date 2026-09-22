"""
Phase 6, Step 42: score the A/B runs (capture_ab_runs.py) with the exact
same quality metrics Step 39 uses offline, so cost and quality are
comparable on the same scale across both arms.

  correctness   GEval, answer vs. expected_facts (score_runs.py's
                CORRECTNESS_CRITERIA, reused verbatim).
  faithfulness  FaithfulnessMetric, answer vs. retrieval_context.

Same context/answer char budgets as score_runs.py, same reason: Groq's
8000 TPM on-demand limit, verified against this exact judge in Step 39.

Judge-neutrality caveat (see capture_ab_runs.py's docstring for the full
statement): this judge (openai/gpt-oss-120b on Groq) shares a provider and
model family with the cheap arm's openai/gpt-oss-20b. Both arms are judged
identically here rather than with different judges per arm, which would
trade this confound for a worse one. Carried into the Step 42 write-up,
not fixed.

Run:
    uv run python -m research_copilot.evals.score_ab_runs
"""

import json
import time
from pathlib import Path

from deepeval.metrics import FaithfulnessMetric, GEval
from deepeval.test_case import LLMTestCase, LLMTestCaseParams
from langfuse import get_client

from research_copilot.evals.judge import GroqJudge
from research_copilot.evals.score_runs import CORRECTNESS_CRITERIA
from research_copilot.evals.scoring_utils import ROW_PACING_SECONDS, THRESHOLD, cap_context, measure_with_backoff

RUNS_PATH = "data/eval_results/step42_ab_runs.jsonl"
DEFAULT_OUT = "data/eval_results/step42_scores.jsonl"

# Same values as score_runs.py's CONTEXT_CHAR_BUDGET / FAITHFULNESS_ANSWER_CHAR_BUDGET.
CONTEXT_CHAR_BUDGET = 12000
FAITHFULNESS_ANSWER_CHAR_BUDGET = 4000


def load_runs(path: str) -> list[dict]:
    """One row per id ("<prompt_id>-<arm>"): later records win."""
    by_id: dict[str, dict] = {}
    with open(path) as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            by_id[row["id"]] = row
    return [row for row in by_id.values() if row.get("status") == "ok"]


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
        "prompt_id": row["prompt_id"],
        "arm": row["arm"],
        "trace_id": row["trace_id"],
        "cost_usd": row["cost_usd"],
        "input_tokens": row["input_tokens"],
        "output_tokens": row["output_tokens"],
        "elapsed_seconds": row["elapsed_seconds"],
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
    runs_path = Path(RUNS_PATH)
    if not runs_path.exists():
        print(f"{runs_path} does not exist yet - nothing to score.")
        return
    runs = load_runs(RUNS_PATH)
    print(f"{len(runs)} run(s) with status=ok to score\n")
    if not runs:
        return

    judge = GroqJudge()
    correctness = GEval(
        name="Correctness",
        criteria=CORRECTNESS_CRITERIA,
        evaluation_params=[LLMTestCaseParams.ACTUAL_OUTPUT, LLMTestCaseParams.EXPECTED_OUTPUT],
        model=judge,
        threshold=THRESHOLD,
    )
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
                f"({'pass' if result['faithfulness_passed'] else 'fail'})  "
                f"cost=${result['cost_usd']:.6f}"
            )
            if i < len(todo):
                time.sleep(ROW_PACING_SECONDS)

    client.flush()
    print(f"\nWrote {out}, pushed scores to Langfuse")


if __name__ == "__main__":
    main()
