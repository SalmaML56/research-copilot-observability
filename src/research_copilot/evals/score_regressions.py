"""
Phase 6, Step 41: the failure-to-dataset loop, part 2 - score confirmed
regression cases against their corrected_expectation.

Only status="confirmed" entries in data/regression_cases.jsonl are scored.
find_regressions.py writes every new entry as status="draft_needs_review"
with an auto-drafted corrected_expectation - this file refuses to use a
draft even if someone forgets to check, by filtering on status here as a
second gate, not just relying on the writer to have been careful.

One GEval, generic and reusable across every regression case regardless of
topic: "does the actual output fulfill the expectation in corrected_
expectation" - unlike Step 39's correctness metric (criteria fixed at
"matches this list of facts"), the expectation text itself is the
per-row variable here (expected_output), so one metric instance covers
every regression case ever added, not just this first batch.

A confirmed regression case is expected to still be failing until someone
actually fixes the underlying bug (out of scope for Phase 6, per the Step
38/39 findings) - this score is proof the check would catch it, not a
claim that it's fixed.

Run:
    uv run python -m research_copilot.evals.score_regressions
"""

import json
import time
from pathlib import Path

from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCase, LLMTestCaseParams
from langfuse import get_client

from research_copilot.evals.judge import GroqJudge
from research_copilot.evals.scoring_utils import ROW_PACING_SECONDS, THRESHOLD, measure_with_backoff

CASES_PATH = "data/regression_cases.jsonl"
DEFAULT_OUT = "data/eval_results/regression_scores.jsonl"

FULFILLMENT_CRITERIA = (
    "Determine whether 'actual output' fulfills the expectation described in "
    "'expected output'. The expectation describes a behavior or completion "
    "requirement, not a specific fact list - judge whether the actual output "
    "satisfies that requirement, and explain concretely why or why not."
)


def load_confirmed_cases(path: str) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    by_id: dict[str, dict] = {}
    with p.open() as f:
        for line in f:
            if line.strip():
                row = json.loads(line)
                by_id[row["id"]] = row
    confirmed = [row for row in by_id.values() if row.get("status") == "confirmed"]
    skipped = len(by_id) - len(confirmed)
    if skipped:
        print(f"skipping {skipped} unconfirmed (draft_needs_review) case(s) - not used for scoring")
    return confirmed


def score_case(row: dict, fulfillment: GEval) -> dict:
    test_case = LLMTestCase(
        input=row["prompt"],
        actual_output=row["answer"],
        expected_output=row["corrected_expectation"],
    )
    measure_with_backoff(fulfillment, test_case)
    return {
        "id": row["id"],
        "source_run_id": row["source_run_id"],
        "trace_id": row["source_trace_id"],
        "corrected_expectation": row["corrected_expectation"],
        "fulfillment_score": fulfillment.score,
        "fulfillment_passed": fulfillment.score >= THRESHOLD,
        "fulfillment_reason": fulfillment.reason,
    }


def push_to_langfuse(client, result: dict) -> None:
    client.create_score(
        trace_id=result["trace_id"],
        name="regression_check",
        value=result["fulfillment_score"],
        data_type="NUMERIC",
        comment=result["fulfillment_reason"],
    )


def main() -> None:
    cases = load_confirmed_cases(CASES_PATH)
    print(f"{len(cases)} confirmed regression case(s) to score\n")
    if not cases:
        return

    judge = GroqJudge()
    fulfillment = GEval(
        name="RegressionFulfillment",
        criteria=FULFILLMENT_CRITERIA,
        evaluation_params=[LLMTestCaseParams.ACTUAL_OUTPUT, LLMTestCaseParams.EXPECTED_OUTPUT],
        model=judge,
        threshold=THRESHOLD,
    )

    client = get_client()
    out = Path(DEFAULT_OUT)
    out.parent.mkdir(parents=True, exist_ok=True)

    already_scored: set[str] = set()
    if out.exists():
        with out.open() as f:
            for line in f:
                if line.strip():
                    already_scored.add(json.loads(line)["id"])
    todo = [row for row in cases if row["id"] not in already_scored]
    if already_scored:
        print(f"resuming: {len(already_scored)} already scored, {len(todo)} remaining\n")

    with out.open("a") as f:
        for i, row in enumerate(todo, 1):
            print(f"[{i}/{len(todo)}] {row['id']}")
            result = score_case(row, fulfillment)
            f.write(json.dumps(result) + "\n")
            f.flush()
            push_to_langfuse(client, result)
            print(
                f"    fulfillment={result['fulfillment_score']:.2f} "
                f"({'pass' if result['fulfillment_passed'] else 'FAIL - regression confirmed'})"
            )
            if i < len(todo):
                time.sleep(ROW_PACING_SECONDS)

    client.flush()
    print(f"\nWrote {out}, pushed scores to Langfuse")


if __name__ == "__main__":
    main()
