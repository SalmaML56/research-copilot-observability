"""
Phase 6, Step 41: the failure-to-dataset loop, part 1 - find failing runs
and draft regression cases for them.

Langfuse-side tagging ("mark this trace as needs-review") is not viable on
this deployment: comments.create validates the target trace through the
same lookup path trace.list/trace.get use, and that's disabled under
Langfuse v4 "events_only" mode - verified directly (404 "Reference object,
TRACE: ... not found"), same root cause as the Step 40 finding. So this
works entirely from the local JSONL files Steps 38-40 already produce,
which already have everything needed (prompt, answer, trace_id, score,
judge's reason) - no Langfuse read required.

A "failure" here is any row in step39_scores.jsonl or online_scores.jsonl
where a metric scored below threshold. For each one, this drafts a
candidate corrected_expectation by asking the judge to generalize its own
failure reason into a reusable expectation statement - generic on purpose,
so score_regressions.py's check isn't tied to any one topic's facts.

The draft is never auto-committed. Every new entry is written with
status="draft_needs_review" and printed with an explicit flag. A human
has to confirm it (edit corrected_expectation and set
status="confirmed") before score_regressions.py will use it - see that
file's filtering.

Run:
    uv run python -m research_copilot.evals.find_regressions
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from research_copilot.evals.judge import GroqJudge

OFFLINE_SCORES_PATH = "data/eval_results/step39_scores.jsonl"
OFFLINE_RUNS_PATH = "data/eval_results/step38_runs.jsonl"
ONLINE_SCORES_PATH = "data/eval_results/online_scores.jsonl"
ONLINE_SAMPLES_PATH = "data/eval_results/online_samples.jsonl"
OUT_PATH = "data/regression_cases.jsonl"

THRESHOLD = 0.5

DRAFT_PROMPT_TEMPLATE = """You are drafting a regression-test expectation for an eval dataset.

An answer was judged to have FAILED an evaluation. Given the prompt and the
judge's reason for the failure, write ONE short, generic sentence
describing what a correct answer should do instead. Make it general enough
to apply to other prompts with the same underlying failure pattern - do
NOT restate this specific topic's facts or details, describe the
behavior/completion expectation the failing answer violated.

Prompt: {prompt}

Judge's failure reason: {reason}

Corrected expectation (one sentence, generic, no topic-specific facts):"""


def _load_jsonl(path: str) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    with p.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def _dedupe_last(rows: list[dict], key: str) -> dict[str, dict]:
    by_key: dict[str, dict] = {}
    for row in rows:
        by_key[row[key]] = row
    return by_key


def find_offline_failures() -> list[dict]:
    scores = _dedupe_last(_load_jsonl(OFFLINE_SCORES_PATH), "id")
    runs = _dedupe_last(_load_jsonl(OFFLINE_RUNS_PATH), "id")
    failures = []
    for run_id, score in scores.items():
        failed_metrics = [m for m in ("correctness", "faithfulness") if not score.get(f"{m}_passed", True)]
        if not failed_metrics:
            continue
        run = runs.get(run_id)
        if run is None:
            continue
        failures.append(
            {
                "source": "offline",
                "source_run_id": run_id,
                "source_trace_id": score["trace_id"],
                "prompt": run["prompt"],
                "answer": run["answer"],
                "failed_metrics": failed_metrics,
                "failure_reason": score[f"{failed_metrics[0]}_reason"],
            }
        )
    return failures


def find_online_failures() -> list[dict]:
    scores = _dedupe_last(_load_jsonl(ONLINE_SCORES_PATH), "id")
    samples = _dedupe_last(_load_jsonl(ONLINE_SAMPLES_PATH), "id")
    failures = []
    for sample_id, score in scores.items():
        failed_metrics = [m for m in ("relevancy", "faithfulness") if not score.get(f"{m}_passed", True)]
        if not failed_metrics:
            continue
        sample = samples.get(sample_id)
        if sample is None:
            continue
        failures.append(
            {
                "source": "online",
                "source_run_id": sample_id,
                "source_trace_id": score["trace_id"],
                "prompt": sample["prompt"],
                "answer": sample["answer"],
                "failed_metrics": failed_metrics,
                "failure_reason": score[f"{failed_metrics[0]}_reason"],
            }
        )
    return failures


def draft_corrected_expectation(judge: GroqJudge, prompt: str, reason: str) -> str:
    draft_prompt = DRAFT_PROMPT_TEMPLATE.format(prompt=prompt, reason=reason)
    return judge.generate(draft_prompt).strip()


def main() -> None:
    out_path = Path(OUT_PATH)
    existing_ids = {row["source_run_id"] for row in _load_jsonl(OUT_PATH)}

    failures = find_offline_failures() + find_online_failures()
    todo = [f for f in failures if f["source_run_id"] not in existing_ids]

    print(f"{len(failures)} failing run(s) found locally, {len(todo)} new (not yet in {out_path})\n")
    if not todo:
        return

    judge = GroqJudge()
    with out_path.open("a") as f:
        for failure in todo:
            draft = draft_corrected_expectation(judge, failure["prompt"], failure["failure_reason"])
            row = {
                "id": f"regression-{failure['source_run_id']}",
                "source": failure["source"],
                "source_run_id": failure["source_run_id"],
                "source_trace_id": failure["source_trace_id"],
                "prompt": failure["prompt"],
                "answer": failure["answer"],
                "failed_metrics": failure["failed_metrics"],
                "failure_reason": failure["failure_reason"],
                "corrected_expectation_draft": draft,
                "corrected_expectation": None,
                "status": "draft_needs_review",
                "added_at": datetime.now(timezone.utc).isoformat(),
            }
            f.write(json.dumps(row) + "\n")
            f.flush()
            print(f"[{failure['source_run_id']}] *** DRAFT - NEEDS HUMAN REVIEW, NOT CONFIRMED ***")
            print(f"    failed: {failure['failed_metrics']}")
            print(f"    drafted corrected_expectation: {draft}\n")

    print(
        f"Wrote {out_path}. All new entries are status=draft_needs_review - "
        f"score_regressions.py will skip them until a human sets "
        f"status=confirmed and fills in corrected_expectation."
    )


if __name__ == "__main__":
    main()
