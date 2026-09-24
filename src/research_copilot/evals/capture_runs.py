"""
Phase 6, Step 38: run dataset prompts through the agent and save everything
an offline eval needs, one JSON object per line:

  answer             final text (correctness judge)
  retrieval_context  raw web_search outputs (faithfulness judge)
  tool_calls         ordered tool names (reused by the Step 39 scorers)
  trace_id           Langfuse trace to write scores back onto

Why a callback collector instead of reading result["messages"]: the
researcher subagent calls web_search, so those ToolMessages are not in the
lead agent's message list. Callbacks propagate into subagents.

Why a pre-chosen trace_id: CallbackHandler exposes no way to read the id back
after the run, but it accepts trace_context={"trace_id": ...}.

Run (first prompt only, safest first cost check):
    uv run python -m research_copilot.evals.capture_runs --limit 1
"""

import argparse
import json
import time
import uuid
from pathlib import Path

from langfuse import get_client
from langfuse.langchain import CallbackHandler

from research_copilot.agents.main_agent import agent
from research_copilot.agents.prompt_registry import prompt_version_stamp
from research_copilot.config.settings import settings
from research_copilot.evals.tool_collector import ToolCollector

DATASET_PATH = "data/test_dataset.jsonl"
DEFAULT_OUT = "data/eval_results/step38_runs.jsonl"


def final_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            b.get("text", "") if isinstance(b, dict) else str(b) for b in content
        )
    return str(content)


def load_dataset() -> list[dict]:
    with open(DATASET_PATH) as f:
        return [json.loads(line) for line in f]


def run_one(entry: dict, run_label: str, extra_callbacks: list = ()) -> dict:
    trace_id = get_client().create_trace_id(seed=f"{run_label}:{entry['id']}")
    collector = ToolCollector()
    row = {
        "id": entry["id"],
        "prompt": entry["prompt"],
        "expected_facts": entry["expected_facts"],
        "run_label": run_label,
        "model_profile": settings.model_profile,
        "prompt_version": prompt_version_stamp(),
        "trace_id": trace_id,
    }
    start = time.time()
    try:
        result = agent.invoke(
            {"messages": [{"role": "user", "content": entry["prompt"]}]},
            config={
                "callbacks": [CallbackHandler(trace_context={"trace_id": trace_id}), collector, *extra_callbacks],
                "metadata": {
                    "langfuse_session_id": f"{run_label}-{entry['id']}",
                    "langfuse_user_id": "eval-capture",
                    "langfuse_tags": [f"prompt_version:{prompt_version_stamp()}"],
                    "prompt_version": prompt_version_stamp(),
                },
            },
        )
        last = result["messages"][-1]
        answer = final_text(last.content)
        row.update(
            status="ok",
            answer=answer,
            retrieval_context=collector.search_outputs,
            tool_calls=collector.tool_calls,
        )
        # Same guard as capture_ab_runs.py (Step 42), missing here until
        # Step 51: an empty last turn means the lead's finalize_report was
        # cut off at max_tokens and never ran. Recorded as "ok" it crashed
        # ci_gate score (GEval rejects an empty actual_output).
        if not answer.strip():
            invalid = [c.get("name") for c in getattr(last, "invalid_tool_calls", None) or []]
            row.update(status="error", error_type="EmptyFinalAnswer",
                       error=f"empty final answer (invalid tool calls: {invalid})")
    except Exception as e:
        row.update(
            status="error",
            error=str(e)[:300],
            error_type=type(e).__name__,
            retrieval_context=collector.search_outputs,
            tool_calls=collector.tool_calls,
        )
    row["elapsed_seconds"] = round(time.time() - start, 1)
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--run-label", default=None, help="default: fresh id per invocation")
    args = parser.parse_args()

    run_label = args.run_label or f"step38-{uuid.uuid4().hex[:8]}"
    batch = load_dataset()[args.start : args.start + args.limit]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    print(f"run_label={run_label} | {len(batch)} prompt(s) | profile={settings.model_profile}\n")
    with out.open("a") as f:
        for i, entry in enumerate(batch, 1):
            print(f"[{i}/{len(batch)}] {entry['id']}: {entry['prompt'][:70]}...")
            row = run_one(entry, run_label)
            f.write(json.dumps(row) + "\n")
            f.flush()
            print(
                f"    -> {row['status']}, {row['elapsed_seconds']}s, "
                f"{len(row['tool_calls'])} tool calls, "
                f"{len(row['retrieval_context'])} search outputs, trace_id={row['trace_id']}"
            )
            if row["status"] == "error":
                print(f"    -> error: {row['error']}")

    get_client().flush()
    print(f"\nAppended to {out}")


if __name__ == "__main__":
    main()
