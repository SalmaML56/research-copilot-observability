"""
Phase 2, Steps 15 & 16.

Step 15: verify the Langfuse CallbackHandler delivers a full delegation
trace (lead -> researcher -> writer -> tools -> model calls) to a freshly
self-hosted local Langfuse instance.

Step 16: verify langfuse_session_id / langfuse_user_id grouping actually
works - two turns under the same session ID should group together in
Langfuse, and a separate session ID should NOT be grouped with them.

Run:
    uv run python -m research_copilot.agents.run_langfuse_grouping_demo
"""
import time
import uuid

from dotenv import load_dotenv
load_dotenv()

from langfuse import Langfuse

from research_copilot.agents.main_agent import agent
from research_copilot.observability.langfuse_setup import get_langfuse_handler


def run_turn(session_id: str, user_id: str, prompt: str) -> str:
    result = agent.invoke(
        {"messages": [{"role": "user", "content": prompt}]},
        config={
            "callbacks": [get_langfuse_handler()],
            "metadata": {
                "langfuse_session_id": session_id,
                "langfuse_user_id": user_id,
            },
        },
    )
    return result["messages"][-1].content


if __name__ == "__main__":
    session_a = f"step16-session-a-{uuid.uuid4().hex[:6]}"
    session_b = f"step16-session-b-{uuid.uuid4().hex[:6]}"
    delegation_session = f"step15-delegation-{uuid.uuid4().hex[:6]}"

    print("=== Step 16: two turns, same session (A) ===")
    r1 = run_turn(session_a, "verify-user-1", "What is 12 * 12? Answer directly, no research needed.")
    print("Turn 1:", r1[:100])
    r2 = run_turn(session_a, "verify-user-1", "What is the square root of 144? Answer directly, no research needed.")
    print("Turn 2:", r2[:100])

    print("\n=== Step 16: one turn, different session (B) ===")
    r3 = run_turn(session_b, "verify-user-2", "What is the capital of Japan? Answer directly, no research needed.")
    print("Turn:", r3[:100])

    print("\n=== Step 15: full delegation task (lead -> researcher -> writer -> tools -> model) ===")
    r4 = run_turn(
        delegation_session,
        "verify-user-1",
        "Research the main causes of the fall of the Roman Empire and write a short report.",
    )
    print("Result:", r4[:150])

    lf = Langfuse()
    lf.flush()
    time.sleep(3)

    print("\n=== Verification via Langfuse Observations API v2 (v4 events_only mode) ===")
    obs_a = lf.api.observations.get_many(session_id=session_a, is_root_observation=True)
    obs_b = lf.api.observations.get_many(session_id=session_b, is_root_observation=True)
    obs_d = lf.api.observations.get_many(session_id=delegation_session, is_root_observation=True)

    print(f"Session A ({session_a}): {len(obs_a.data)} root observations (expected: 2)")
    print(f"Session B ({session_b}): {len(obs_b.data)} root observations (expected: 1)")
    print(f"Delegation session ({delegation_session}): {len(obs_d.data)} root observations (expected: 1)")

    assert len(obs_a.data) == 2, f"Session A grouping FAILED: expected 2, got {len(obs_a.data)}"
    assert len(obs_b.data) == 1, f"Session B grouping FAILED: expected 1, got {len(obs_b.data)}"
    assert len(obs_d.data) == 1, f"Delegation session grouping FAILED: expected 1, got {len(obs_d.data)}"
    print("\nALL SESSION GROUPING ASSERTIONS PASSED")
