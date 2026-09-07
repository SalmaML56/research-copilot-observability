"""
Phase 2, step 18: run a batch of dataset prompts through the agent, each
traced to its own Langfuse session (named after the prompt's dataset id),
so they can be found and reviewed individually in the Langfuse UI
afterward.

Run (first 3 prompts, safest for a first cost check):
    uv run python -m research_copilot.agents.run_eval_batch --limit 3
"""

import argparse
import json
import time

from research_copilot.agents.main_agent import agent
from research_copilot.observability.langfuse_setup import get_langfuse_handler

DATASET_PATH = "data/test_dataset.jsonl"


def load_dataset() -> list[dict]:
    with open(DATASET_PATH) as f:
        return [json.loads(line) for line in f]


def run_one(entry: dict) -> dict:
    session_id = f"eval-{entry['id']}"
    start = time.time()
    try:
        result = agent.invoke(
            {"messages": [{"role": "user", "content": entry["prompt"]}]},
            config={
                "callbacks": [get_langfuse_handler()],
                "metadata": {
                    "langfuse_session_id": session_id,
                    "langfuse_user_id": "eval-batch",
                },
            },
        )
        elapsed = time.time() - start
        final_text = result["messages"][-1].content
        return {
            "id": entry["id"],
            "session_id": session_id,
            "status": "ok",
            "elapsed_seconds": round(elapsed, 1),
            "answer_length_chars": len(final_text),
        }
    except Exception as e:
        elapsed = time.time() - start
        return {
            "id": entry["id"],
            "session_id": session_id,
            "status": "error",
            "elapsed_seconds": round(elapsed, 1),
            "error": str(e)[:300],
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--limit", type=int, default=3)
    args = parser.parse_args()

    dataset = load_dataset()
    batch = dataset[args.start : args.start + args.limit]

    print(f"Running {len(batch)} prompt(s), starting at index {args.start}\n")

    results = []
    for i, entry in enumerate(batch, 1):
        print(f"[{i}/{len(batch)}] {entry['id']}: {entry['prompt'][:70]}...")
        r = run_one(entry)
        results.append(r)
        status_line = f"    -> {r['status']}, {r['elapsed_seconds']}s"
        if r["status"] == "error":
            status_line += f", error: {r['error']}"
        print(status_line)
        print(f"    -> Langfuse session_id to look up: {r['session_id']}\n")

    print("=== Summary ===")
    ok_count = sum(1 for r in results if r["status"] == "ok")
    print(f"{ok_count}/{len(results)} succeeded")
    total_time = sum(r["elapsed_seconds"] for r in results)
    print(f"Total time: {round(total_time, 1)}s")


if __name__ == "__main__":
    main()
