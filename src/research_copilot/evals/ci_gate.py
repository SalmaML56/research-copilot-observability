"""
Phase 8, Step 49: the PR eval gate. Run by .github/workflows/eval-gate.yml.

    capture  one dataset prompt through the real agent (DeepSeek), one JSONL
             row out. The workflow runs one per prompt as a matrix, so the
             three ~15-minute runs happen in parallel on separate runners.
    score    correctness (Step 39's GEval, Groq judge) for every captured
             row, then the verdict. Sequential: the judge has an 8000 TPM cap.

Verdicts (plan Q1, Q2, Q9):
    pass          every row scored, mean correctness >= threshold
    fail          mean correctness < threshold, OR a run crashed with a
                  non-provider error, OR a run blew its cost budget (a
                  runaway loop is a real regression, not bad luck)
    inconclusive  something outside the PR's control stopped a row from
                  being scored: every web_search in the run failed (the
                  DuckDuckGo block on cloud IPs, tools.py), a provider/
                  network error, or a judge error after retries. Exit 0 with
                  a warning - never gate on a partial mean of 1-2 rows.

Run locally:
    uv run python -m research_copilot.evals.ci_gate capture --id rc-001 --out-dir runs/
    uv run python -m research_copilot.evals.ci_gate score --runs-dir runs/ --threshold 0.3
"""

import argparse
import json
import os
import sys
from pathlib import Path

GATE_IDS = ("rc-001", "rc-002", "rc-003")  # plan Q3: 3 prompts
# Step 42's primary arm: mean $0.22/run, max $0.57. A run past this is
# looping, and gets stopped instead of billing on.
RUN_BUDGET_USD = 1.00
SEARCH_FAILED_PREFIX = "Search failed after retries"
# Exception class names from the provider SDKs / httpx that mean "the API or
# network failed", not "the code under test is broken".
PROVIDER_ERROR_TYPES = {
    "APIConnectionError", "APITimeoutError", "RateLimitError", "InternalServerError",
    "APIStatusError", "ServiceUnavailableError", "ConnectError", "ConnectTimeout",
    "ReadTimeout", "RemoteProtocolError", "TimeoutException",
}


class BudgetExceeded(RuntimeError):
    pass


def row_problem(row: dict) -> tuple[str, str] | None:
    """(kind, reason) when a captured row can't be scored, else None.
    kind is "fail" or "inconclusive"."""
    if row.get("status") != "ok":
        error_type = row.get("error_type", "")
        reason = f"{error_type}: {row.get('error', '')}"
        if error_type == BudgetExceeded.__name__:
            return "fail", reason
        if error_type in PROVIDER_ERROR_TYPES:
            return "inconclusive", reason
        return "fail", reason
    searches = row.get("retrieval_context") or []
    if searches and all(str(s).startswith(SEARCH_FAILED_PREFIX) for s in searches):
        return "inconclusive", f"all {len(searches)} web_search calls failed (search provider blocked?)"
    return None


def decide(rows: list[dict], threshold: float, expected_ids=GATE_IDS) -> dict:
    """Pure verdict logic, unit-tested in tests/test_ci_gate.py. Rows here
    have been through scoring: a scored row has correctness_score, an
    unscorable one has problem=(kind, reason)."""
    by_id = {row["id"]: row for row in rows}
    problems = []
    for expected in expected_ids:
        row = by_id.get(expected)
        if row is None:
            problems.append(("inconclusive", expected, "no captured row (capture job failed or was cancelled)"))
        elif row.get("problem"):
            kind, reason = row["problem"]
            problems.append((kind, expected, reason))
    scores = [by_id[i]["correctness_score"] for i in expected_ids
              if i in by_id and by_id[i].get("correctness_score") is not None]
    mean = sum(scores) / len(scores) if scores else None

    if any(kind == "fail" for kind, _, _ in problems):
        verdict = "fail"
    elif problems:
        verdict = "inconclusive"
    elif mean < threshold:
        verdict = "fail"
    else:
        verdict = "pass"
    return {"verdict": verdict, "mean": mean, "threshold": threshold, "scored": len(scores),
            "expected": len(expected_ids), "problems": problems}


def capture(entry_id: str, out_dir: Path) -> None:
    # Heavy imports only here: `score` and the unit tests must not need
    # DEEPSEEK_API_KEY (main_agent validates settings at import).
    from research_copilot.evals.capture_ab_runs import TokenCostCollector
    from research_copilot.evals.capture_runs import load_dataset, run_one
    from research_copilot.config.settings import settings

    class BudgetGuard(TokenCostCollector):
        raise_error = True  # LangChain swallows callback exceptions otherwise

        def on_llm_end(self, response, **kwargs):
            super().on_llm_end(response, **kwargs)
            if self.cost_usd > RUN_BUDGET_USD:
                raise BudgetExceeded(f"run cost ${self.cost_usd:.2f} > budget ${RUN_BUDGET_USD:.2f}")

    entry = next(e for e in load_dataset() if e["id"] == entry_id)
    guard = BudgetGuard(settings.primary_model_name)
    run_label = f"ci-{os.getenv('GITHUB_RUN_ID', 'local')}-{os.getenv('GITHUB_RUN_ATTEMPT', '1')}"
    row = run_one(entry, run_label, extra_callbacks=[guard])
    row.update(cost_usd=round(guard.cost_usd, 6), unpriced_calls=guard.unpriced_calls)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{entry_id}.jsonl").write_text(json.dumps(row) + "\n")
    print(f"{entry_id}: status={row['status']} {row['elapsed_seconds']}s ${row['cost_usd']:.4f} "
          f"tools={len(row['tool_calls'])} searches={len(row['retrieval_context'])} "
          f"prompt_version={row['prompt_version']}")
    if row["status"] != "ok":
        print(f"  error: {row.get('error_type')}: {row.get('error')}")


def score(runs_dir: Path, threshold: float) -> dict:
    from groq import APIStatusError

    from research_copilot.evals.judge import GroqJudge
    from research_copilot.evals.score_runs import correctness_metric
    from research_copilot.evals.scoring_utils import measure_with_backoff
    from deepeval.test_case import LLMTestCase

    rows = [json.loads(line) for f in sorted(runs_dir.glob("*.jsonl"))
            for line in f.read_text().splitlines() if line.strip()]
    metric = correctness_metric(GroqJudge())
    for row in rows:
        problem = row_problem(row)
        if problem:
            row["problem"] = problem
            continue
        case = LLMTestCase(input=row["prompt"], actual_output=row["answer"],
                           expected_output="\n".join(row["expected_facts"]))
        try:
            measure_with_backoff(metric, case)
        except APIStatusError as e:
            row["problem"] = ("inconclusive", f"judge error after retries: {e}"[:300])
            continue
        row["correctness_score"] = metric.score
        row["correctness_reason"] = metric.reason
        print(f"{row['id']}: correctness={metric.score:.2f}")
    result = decide(rows, threshold)
    result["rows"] = rows
    return result


def summary_markdown(result: dict) -> str:
    icon = {"pass": "✅", "fail": "❌", "inconclusive": "⚠️"}[result["verdict"]]
    mean = "n/a" if result["mean"] is None else f"{result['mean']:.2f}"
    lines = [
        f"## {icon} Eval gate: {result['verdict'].upper()}",
        "",
        f"Mean correctness **{mean}** over {result['scored']}/{result['expected']} prompts "
        f"(threshold {result['threshold']:.2f}).",
        "",
        "| Prompt | Correctness | Status | Cost | Time | Searches | prompt_version |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in sorted(result["rows"], key=lambda r: r["id"]):
        s = row.get("correctness_score")
        cell = f"{s:.2f}" if s is not None else "-"
        status = row["problem"][0] if row.get("problem") else row.get("status")
        lines.append(f"| {row['id']} | {cell} | {status} | ${row.get('cost_usd', 0):.3f} | "
                     f"{row.get('elapsed_seconds', '-')}s | {len(row.get('retrieval_context') or [])} | "
                     f"`{row.get('prompt_version', '?')}` |")
    if result["problems"]:
        lines += ["", "**Not scored:**"]
        lines += [f"- {pid} ({kind}): {reason}" for kind, pid, reason in result["problems"]]
    reasons = [(r["id"], r["correctness_reason"]) for r in result["rows"] if r.get("correctness_reason")]
    if reasons:
        lines += ["", "<details><summary>Judge reasons</summary>", ""]
        lines += [f"- **{pid}**: {reason}" for pid, reason in sorted(reasons)]
        lines += ["", "</details>"]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("capture")
    c.add_argument("--id", required=True, choices=GATE_IDS)
    c.add_argument("--out-dir", type=Path, required=True)
    s = sub.add_parser("score")
    s.add_argument("--runs-dir", type=Path, required=True)
    s.add_argument("--threshold", type=float, required=True)
    args = parser.parse_args()

    if args.cmd == "capture":
        capture(args.id, args.out_dir)
        return 0  # the verdict belongs to `score`; a failed run is a row, not a crash

    result = score(args.runs_dir, args.threshold)
    markdown = summary_markdown(result)
    print(markdown)
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(markdown)
    (args.runs_dir / "gate_result.json").write_text(json.dumps(result, indent=2, default=str))
    if result["verdict"] == "inconclusive":
        print("::warning title=Eval gate inconclusive::"
              + "; ".join(f"{pid}: {reason}" for _, pid, reason in result["problems"])[:900])
    return 1 if result["verdict"] == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
