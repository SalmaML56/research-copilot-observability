"""
Phase 6, Step 42: compare the two A/B arms (capture_ab_runs.py +
score_ab_runs.py output) on cost, quality, and completion rate.

Reads both data files fresh each run (no separate state) since this is a
read-only report, not a capture/score step that needs resuming.

Run:
    uv run python -m research_copilot.evals.compare_ab_runs
"""

import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

RUNS_PATH = "data/eval_results/step42_ab_runs.jsonl"
SCORES_PATH = "data/eval_results/step42_scores.jsonl"


def load_jsonl(path: str) -> list[dict]:
    rows = []
    p = Path(path)
    if not p.exists():
        return rows
    with p.open() as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def main() -> None:
    runs = load_jsonl(RUNS_PATH)
    scores = load_jsonl(SCORES_PATH)
    scores_by_id = {s["id"]: s for s in scores}

    # Completion rate per arm: one attempt counted per prompt_id (a prompt
    # retried after an error, like rc-001-cheap, counts once - its last
    # attempt decides ok/error).
    latest_by_id: dict[str, dict] = {}
    for row in runs:
        latest_by_id[row["id"]] = row  # later lines win, same rule as score_ab_runs.load_runs

    by_arm: dict[str, list[dict]] = defaultdict(list)
    for row in latest_by_id.values():
        by_arm[row["arm"]].append(row)

    print("=" * 72)
    print("Step 42 A/B comparison: primary (DeepSeek deepseek-chat) vs cheap (Groq openai/gpt-oss-20b)")
    print("=" * 72)

    for arm in sorted(by_arm):
        rows = by_arm[arm]
        ok_rows = [r for r in rows if r["status"] == "ok"]
        error_rows = [r for r in rows if r["status"] == "error"]
        print(f"\n--- arm={arm} ---")
        print(f"completion: {len(ok_rows)}/{len(rows)} prompts succeeded")
        if error_rows:
            error_types = Counter(r["error"].split(" - ", 1)[0] for r in error_rows)
            print(f"error breakdown: {dict(error_types)}")

        if not ok_rows:
            print("no successful runs - cost/quality cannot be computed for this arm")
            continue

        costs = [r["cost_usd"] for r in ok_rows]
        elapsed = [r["elapsed_seconds"] for r in ok_rows]
        print(f"cost_usd: mean=${statistics.mean(costs):.6f}  total=${sum(costs):.6f}")
        print(f"elapsed_seconds: mean={statistics.mean(elapsed):.1f}  max={max(elapsed):.1f}")

        scored = [scores_by_id[r["id"]] for r in ok_rows if r["id"] in scores_by_id]
        unscored = [r["id"] for r in ok_rows if r["id"] not in scores_by_id]
        if unscored:
            print(f"WARNING: {len(unscored)} ok run(s) have no score row yet: {unscored}")
        if scored:
            correctness = [s["correctness_score"] for s in scored]
            faithfulness = [s["faithfulness_score"] for s in scored]
            passed = sum(1 for s in scored if s["correctness_passed"])
            print(f"correctness: mean={statistics.mean(correctness):.2f}  pass={passed}/{len(scored)}")
            print(f"faithfulness: mean={statistics.mean(faithfulness):.2f}")

    print("\n" + "=" * 72)
    primary_ok = [r for r in by_arm.get("primary", []) if r["status"] == "ok"]
    cheap_ok = [r for r in by_arm.get("cheap", []) if r["status"] == "ok"]
    if primary_ok and not cheap_ok:
        print(
            "VERDICT: cheap arm produced zero completed runs "
            f"(0/{len(by_arm.get('cheap', []))}) - no cost/quality comparison is possible. "
            "The finding IS the result: this workload does not fit the cheap arm's "
            "provider-side rate limit, independent of answer quality."
        )
    print("=" * 72)


if __name__ == "__main__":
    main()
