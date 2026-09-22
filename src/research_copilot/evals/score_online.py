"""
Phase 6, Step 40: score the online (live, sampled) runs captured inline by
api/main.py and write the scores back onto their Langfuse traces.

Two metrics per row, both judged by GroqJudge (see judge.py):

  relevancy     DeepEval's AnswerRelevancyMetric, answer vs. prompt. Unlike
                Step 39's offline correctness (GEval vs. expected_facts),
                live traffic has no reference facts for an arbitrary user
                topic - relevancy needs no reference, only the question and
                the answer.
  faithfulness  DeepEval's FaithfulnessMetric, answer vs. retrieval_context
                (the captured web_search outputs) - same metric Step 39
                uses offline, same reason: catches claims the answer makes
                that the search results don't support.

Threshold 0.5, descriptive only - same as Step 39, gating is out of scope.

Same Groq 8000 TPM constraint Step 39 hit applies here too: AnswerRelevancy
extracts one "statement" per sentence-ish unit of actual_output, then
verdicts each against the input, much like FaithfulnessMetric's claims step
- so a long live answer risks the same max_tokens=4096 verdicts-JSON
failure rc-004 hit offline. Both metrics' actual_output is capped for the
same reason FAITHFULNESS_ANSWER_CHAR_BUDGET exists in score_runs.py.

Run:
    uv run python -m research_copilot.evals.score_online
"""

import json
import time
from pathlib import Path

from deepeval.metrics import AnswerRelevancyMetric, FaithfulnessMetric
from deepeval.test_case import LLMTestCase
from langfuse import get_client

from research_copilot.evals.judge import GroqJudge
from research_copilot.evals.scoring_utils import (
    ROW_PACING_SECONDS,
    THRESHOLD,
    cap_context,
    measure_with_backoff,
)

SAMPLES_PATH = "data/eval_results/online_samples.jsonl"
DEFAULT_OUT = "data/eval_results/online_scores.jsonl"

# Same budgets as score_runs.py, same reason (see module docstring and
# score_runs.py's CONTEXT_CHAR_BUDGET/FAITHFULNESS_ANSWER_CHAR_BUDGET
# comments for the live evidence behind these numbers) - live answers are
# arbitrary length, so there's no reason to assume they're safely short.
CONTEXT_CHAR_BUDGET = 12000
ANSWER_CHAR_BUDGET = 4000


def load_samples(path: str) -> list[dict]:
    """One row per id: later records win over earlier ones (in case a
    thread_id somehow got captured twice)."""
    by_id: dict[str, dict] = {}
    with open(path) as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            by_id[row["id"]] = row
    return list(by_id.values())


def score_row(row: dict, relevancy: AnswerRelevancyMetric, faithfulness: FaithfulnessMetric) -> dict:
    capped_answer = row["answer"][:ANSWER_CHAR_BUDGET]
    relevancy_case = LLMTestCase(
        input=row["prompt"],
        actual_output=capped_answer,
    )
    faithfulness_case = LLMTestCase(
        input=row["prompt"],
        actual_output=capped_answer,
        retrieval_context=cap_context(row["retrieval_context"], CONTEXT_CHAR_BUDGET),
    )

    measure_with_backoff(relevancy, relevancy_case)
    measure_with_backoff(faithfulness, faithfulness_case)

    return {
        "id": row["id"],
        "trace_id": row["trace_id"],
        "relevancy_score": relevancy.score,
        "relevancy_passed": relevancy.score >= THRESHOLD,
        "relevancy_reason": relevancy.reason,
        "faithfulness_score": faithfulness.score,
        "faithfulness_passed": faithfulness.score >= THRESHOLD,
        "faithfulness_reason": faithfulness.reason,
    }


def push_to_langfuse(client, result: dict) -> None:
    client.create_score(
        trace_id=result["trace_id"],
        name="answer_relevancy",
        value=result["relevancy_score"],
        data_type="NUMERIC",
        comment=result["relevancy_reason"],
    )
    client.create_score(
        trace_id=result["trace_id"],
        name="faithfulness",
        value=result["faithfulness_score"],
        data_type="NUMERIC",
        comment=result["faithfulness_reason"],
    )


def main() -> None:
    samples_path = Path(SAMPLES_PATH)
    if not samples_path.exists():
        print(f"{samples_path} does not exist yet - no sampled live runs captured. Nothing to score.")
        return

    samples = load_samples(SAMPLES_PATH)
    if not samples:
        print(f"{samples_path} is empty - no sampled live runs captured yet. Nothing to score.")
        return
    print(f"{len(samples)} sampled online run(s) to score\n")

    judge = GroqJudge()
    relevancy = AnswerRelevancyMetric(model=judge, threshold=THRESHOLD, async_mode=False)
    # async_mode=False: same reason as score_runs.py - truths/claims (here,
    # statements/verdicts) extraction otherwise fires concurrently, doubling
    # peak simultaneous token spend against the same 8000 TPM budget.
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
    todo = [row for row in samples if row["id"] not in already_scored]
    if already_scored:
        print(f"resuming: {len(already_scored)} already scored, {len(todo)} remaining\n")

    with out.open("a") as f:
        for i, row in enumerate(todo, 1):
            print(f"[{i}/{len(todo)}] {row['id']}")
            result = score_row(row, relevancy, faithfulness)
            f.write(json.dumps(result) + "\n")
            f.flush()
            push_to_langfuse(client, result)
            print(
                f"    relevancy={result['relevancy_score']:.2f} "
                f"({'pass' if result['relevancy_passed'] else 'fail'})  "
                f"faithfulness={result['faithfulness_score']:.2f} "
                f"({'pass' if result['faithfulness_passed'] else 'fail'})"
            )
            if i < len(todo):
                time.sleep(ROW_PACING_SECONDS)

    client.flush()
    print(f"\nWrote {out}, pushed scores to Langfuse")


if __name__ == "__main__":
    main()
