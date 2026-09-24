"""Step 51: first pass over a bad trace (docs/step51_bad_trace_runbook.md).

    uv run python scripts/phase8/inspect_trace.py <trace_id>

Pulls every observation of one trace from Langfuse and prints:
  - tool spans that actually executed, in order, with counts
  - invalid_tool_calls on any generation: tool calls the model emitted that
    LangChain could not parse, so they never ran (the Step 51 root cause:
    a write_file cut off at max_tokens)
  - what each `task` (subagent) handed back to the lead agent

Uses the v2 observations endpoint: this self-hosted Langfuse runs v4
events_only mode, where GET /api/public/traces/<id> and v1 /observations
return "not available".
"""

import json
import os
import sys
from collections import Counter

import httpx
from dotenv import load_dotenv

load_dotenv()


def fetch_observations(trace_id: str) -> list[dict]:
    auth = (os.environ["LANGFUSE_PUBLIC_KEY"], os.environ["LANGFUSE_SECRET_KEY"])
    url = os.environ.get("LANGFUSE_HOST", "http://localhost:3000") + "/api/public/v2/observations"
    observations, cursor = [], None
    while True:
        params = {"traceId": trace_id, "limit": 100, "fields": "core,basic,io"}
        if cursor:
            params["cursor"] = cursor
        response = httpx.get(url, params=params, auth=auth, timeout=30)
        response.raise_for_status()
        body = response.json()
        observations += body["data"]
        cursor = (body.get("meta") or {}).get("cursor")
        if not cursor or not body["data"]:
            return observations


def as_message(output) -> dict:
    if isinstance(output, str):
        try:
            output = json.loads(output)
        except ValueError:
            return {}
    return output if isinstance(output, dict) else {}


def main() -> int:
    trace_id = sys.argv[1]
    observations = sorted(fetch_observations(trace_id), key=lambda o: o["startTime"])
    if not observations:
        print(f"no observations for trace {trace_id} (wrong id, or dropped by tail sampling?)")
        return 1
    tools = [o for o in observations if o["type"] == "TOOL"]
    print(f"trace {trace_id}: {len(observations)} observations, session {observations[0].get('sessionId')}")
    print("\nexecuted tools:", dict(Counter(o["name"] for o in tools)))

    print("\ninvalid tool calls (emitted by the model, never executed):")
    found = False
    for o in observations:
        if o["type"] != "GENERATION":
            continue
        for call in as_message(o.get("output")).get("invalid_tool_calls") or []:
            found = True
            error = (call.get("error") or "").strip().splitlines()
            print(f"  {o['startTime']} {call['name']}: args {len(call.get('args') or '')} chars; "
                  f"{error[-2] if len(error) > 1 else error}")
    if not found:
        print("  none")

    print("\nsubagent handoffs (task tool output):")
    for o in tools:
        if o["name"] == "task":
            text = json.dumps(o.get("output"))
            messages = (as_message(o.get("output")).get("update") or {}).get("messages") or []
            if messages:
                text = messages[-1].get("content", text)
            print(f"  {o['startTime']}: {str(text)[:300]!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
