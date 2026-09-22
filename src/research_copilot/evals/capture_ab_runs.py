"""
Phase 6, Step 42: A/B test - frontier model (primary, DeepSeek deepseek-chat)
vs. open-weight model (cheap, Groq openai/gpt-oss-20b) on cost and quality.

Reuses the same 5 prompts already captured for Step 38 (rc-001..rc-005),
paired: same prompt, two models, so any cost/quality difference is
attributable to the model, not prompt-difficulty variance.

Why this doesn't reuse main_agent.agent: that module-level `agent` object
is a singleton baked to whichever MODEL_PROFILE was set at import time -
switching the env var mid-process does nothing to an already-built agent
(verified by reading main_agent.py: `agent = create_deep_agent(model=
settings.default_model, ...)` runs once, at import). This builds two
independent agent instances directly instead, one per model, reusing the
exact same subagents/tools/middleware/system_prompt main_agent.py wires
up. Subagents inherit the parent's model unless they specify their own
(verified against deepagents' SubAgent type - "model": NotRequired[...],
"Override the main agent's model") - researcher/writer specify none, so
each arm's subagents genuinely run on that arm's model too, not a mix.

Why cost is computed locally, not read from a span: capture_runs.py-style
runs never call setup_otel_instrumentation() (confirmed by tracing the
import chain - main_agent.py has no such import), so Step 34's
Collector-side gen_ai.usage.cost_usd is never produced for them.
TokenCostCollector below extracts token usage the same way
GenAIMetricsCallbackHandler.on_llm_end does, and prices it with Step 34's
exact, already-verified rate table (docs/step34_cost_model.md) rather
than re-deriving rates.

Judge-neutrality caveat (stated here, not hidden - see the Step 42
write-up for the full discussion): quality scoring for both arms
(score_ab_runs.py) reuses the same GroqJudge (openai/gpt-oss-120b) Step 39
uses. That judge shares a provider and model family with the cheap arm's
openai/gpt-oss-20b - flagged in judge.py's own docstring as a known,
unresolved neutrality gap. Using a different judge per arm would swap this
confound for a worse one (the judge itself becoming a second independent
variable), so both arms are judged identically.

Run (one prompt, one arm - safest first cost check):
    uv run python -m research_copilot.evals.capture_ab_runs --limit 1
"""

import argparse
import json
import time
import uuid
from pathlib import Path
from typing import Any

from langchain.agents.middleware import SummarizationMiddleware, TodoListMiddleware
from langchain_core.callbacks import BaseCallbackHandler
from langfuse import get_client
from langfuse.langchain import CallbackHandler

from deepagents import create_deep_agent
from research_copilot.agents.subagents import LEAD_AGENT_SYSTEM_PROMPT, researcher, writer
from research_copilot.agents.tools import finalize_report
from research_copilot.config.settings import settings
from research_copilot.evals.tool_collector import ToolCollector

DATASET_PATH = "data/test_dataset.jsonl"
DATASET_LIMIT = 5  # rc-001..rc-005, matching Step 38's scope decision
DEFAULT_OUT = "data/eval_results/step42_ab_runs.jsonl"

# Step 34's exact rate table (docs/step34_cost_model.md), reused verbatim -
# not re-derived. Keyed on the model name as REPORTED by the provider, same
# reason Step 34 keys the Collector's rate table that way: DeepSeek reports
# "deepseek-flash" on live responses even when "deepseek-chat" was
# requested (a provider-side alias, priced identically).
RATE_TABLE_USD_PER_TOKEN = {
    "deepseek-chat": (0.00000027, 0.0000011),
    "deepseek-flash": (0.00000027, 0.0000011),
    "openai/gpt-oss-20b": (0.0000001, 0.0000005),
}

ARMS = {
    "primary": {"model_factory": settings.get_primary_model, "configured_name": settings.primary_model_name},
    "cheap": {"model_factory": settings.get_cheap_model, "configured_name": settings.cheap_model_name},
}


class TokenCostCollector(BaseCallbackHandler):
    """Same token-usage extraction GenAIMetricsCallbackHandler.on_llm_end
    uses (observability/metrics_setup.py), reimplemented locally rather
    than imported: that handler writes straight to an OTel histogram, and
    this needs a local running total instead, priced with Step 34's table
    (unpriced -> None, never a silent $0 - same rule Step 34 follows)."""

    def __init__(self, configured_model_name: str) -> None:
        self.configured_model_name = configured_model_name
        self.input_tokens = 0
        self.output_tokens = 0
        self.cost_usd = 0.0
        self.unpriced_calls = 0

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        token_usage = None
        if getattr(response, "llm_output", None):
            token_usage = response.llm_output.get("token_usage")
        reported_name = None
        if getattr(response, "llm_output", None):
            reported_name = response.llm_output.get("model_name") or response.llm_output.get("model")
        if token_usage is None and response.generations:
            gen = response.generations[0][0]
            msg = getattr(gen, "message", None)
            usage_metadata = getattr(msg, "usage_metadata", None) if msg else None
            if usage_metadata:
                token_usage = {
                    "prompt_tokens": usage_metadata.get("input_tokens"),
                    "completion_tokens": usage_metadata.get("output_tokens"),
                }

        if not token_usage:
            return
        input_tokens = token_usage.get("prompt_tokens") or 0
        output_tokens = token_usage.get("completion_tokens") or 0
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens

        model_name = reported_name or self.configured_model_name
        rates = RATE_TABLE_USD_PER_TOKEN.get(model_name)
        if rates is None:
            self.unpriced_calls += 1
            return
        input_rate, output_rate = rates
        self.cost_usd += input_tokens * input_rate + output_tokens * output_rate


def load_dataset() -> list[dict]:
    with open(DATASET_PATH) as f:
        return [json.loads(line) for line in f][:DATASET_LIMIT]


def build_agent(model):
    return create_deep_agent(
        model=model,
        tools=[finalize_report],
        subagents=[researcher, writer],
        middleware=[
            TodoListMiddleware(),
            SummarizationMiddleware(model=model, trigger=("tokens", 30000), keep=("messages", 15)),
        ],
        system_prompt=LEAD_AGENT_SYSTEM_PROMPT,
    )


def final_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    return str(content)


def run_one(agent, entry: dict, arm: str, configured_model_name: str, run_label: str) -> dict:
    trace_id = get_client().create_trace_id(seed=f"{run_label}:{entry['id']}:{arm}")
    tool_collector = ToolCollector()
    cost_collector = TokenCostCollector(configured_model_name)
    row = {
        "id": f"{entry['id']}-{arm}",
        "prompt_id": entry["id"],
        "arm": arm,
        "configured_model_name": configured_model_name,
        "prompt": entry["prompt"],
        "expected_facts": entry["expected_facts"],
        "run_label": run_label,
        "trace_id": trace_id,
    }
    start = time.time()
    try:
        result = agent.invoke(
            {"messages": [{"role": "user", "content": entry["prompt"]}]},
            config={
                "callbacks": [
                    CallbackHandler(trace_context={"trace_id": trace_id}),
                    tool_collector,
                    cost_collector,
                ],
                "metadata": {
                    "langfuse_session_id": f"{run_label}-{entry['id']}-{arm}",
                    "langfuse_user_id": "eval-capture-ab",
                },
            },
        )
        row.update(
            status="ok",
            answer=final_text(result["messages"][-1].content),
            retrieval_context=tool_collector.search_outputs,
            tool_calls=tool_collector.tool_calls,
        )
    except Exception as e:
        row.update(
            status="error",
            error=str(e)[:300],
            retrieval_context=tool_collector.search_outputs,
            tool_calls=tool_collector.tool_calls,
        )
    row.update(
        elapsed_seconds=round(time.time() - start, 1),
        input_tokens=cost_collector.input_tokens,
        output_tokens=cost_collector.output_tokens,
        cost_usd=cost_collector.cost_usd,
        unpriced_calls=cost_collector.unpriced_calls,
    )
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="max new (prompt, arm) pairs this invocation")
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--run-label", default=None)
    args = parser.parse_args()

    if not settings.deepseek_api_key:
        raise RuntimeError("DEEPSEEK_API_KEY not set - needed for the primary arm.")
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY not set - needed for the cheap arm.")

    run_label = args.run_label or f"step42-{uuid.uuid4().hex[:8]}"
    dataset = load_dataset()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    already_done: set[str] = set()
    if out.exists():
        with out.open() as f:
            for line in f:
                if line.strip():
                    row = json.loads(line)
                    if row.get("status") == "ok":
                        already_done.add(row["id"])

    plan = [(entry, arm) for entry in dataset for arm in ARMS]
    todo = [(entry, arm) for entry, arm in plan if f"{entry['id']}-{arm}" not in already_done]
    if args.limit is not None:
        todo = todo[: args.limit]

    print(f"run_label={run_label} | {len(already_done)} already done, {len(todo)} to run this invocation\n")

    with out.open("a") as f:
        for i, (entry, arm) in enumerate(todo, 1):
            agent = build_agent(ARMS[arm]["model_factory"]())
            configured_name = ARMS[arm]["configured_name"]
            print(f"[{i}/{len(todo)}] {entry['id']} / {arm} ({configured_name}): {entry['prompt'][:60]}...")
            row = run_one(agent, entry, arm, configured_name, run_label)
            f.write(json.dumps(row) + "\n")
            f.flush()
            print(
                f"    -> {row['status']}, {row['elapsed_seconds']}s, "
                f"{row['input_tokens']}in/{row['output_tokens']}out tokens, "
                f"${row['cost_usd']:.6f}, {len(row['tool_calls'])} tool calls, "
                f"trace_id={row['trace_id']}"
            )
            if row["status"] == "error":
                print(f"    -> error: {row['error']}")

    get_client().flush()
    print(f"\nAppended to {out}")


if __name__ == "__main__":
    main()
