"""
Phase 1, step 11: streaming + typed events.

Uses a NEW thread_id (separate from step 10's demo threads) so this run
doesn't collide with any already-paused/resumed interrupt state.

Verified API (via inspect.getsource on the real installed langgraph):
  - stream_mode accepts a list, e.g. ["updates", "messages"]
  - subgraphs=True makes events arrive as (namespace, mode, data) tuples,
    where `namespace` is a tuple of node paths — this is how we detect
    subagent activity (the researcher/writer subagents run as nested
    subgraphs invoked via the built-in `task` tool).

Note: this task still has interrupt_on={"finalize_report": True} wired in
(inherited from build_agent()), so the run WILL pause before finalize_report
completes, same as step 10 — that's expected, not a bug in this script.

Run:
    uv run python -m research_copilot.agents.run_streaming_demo
"""

from langgraph.checkpoint.sqlite import SqliteSaver

from research_copilot.agents.checkpointed_agent import build_agent, CHECKPOINT_DB_PATH

THREAD_ID = "phase1-step11-streaming-demo"


def label_for(namespace: tuple, mode: str) -> str:
    """Turn a raw (namespace, mode) into a short human-readable label."""
    if not namespace:
        location = "lead-agent"
    else:
        location = " > ".join(part.split(":")[0] for part in namespace)
    return f"[{location}] ({mode})"


def main() -> None:
    task = (
        "Research small modular nuclear reactors (SMRs) briefly: what "
        "they are and one leading company. Save notes to 'smr_notes.md', "
        "then write a short final report."
    )

    with SqliteSaver.from_conn_string(CHECKPOINT_DB_PATH) as checkpointer:
        agent = build_agent(checkpointer)
        config = {"configurable": {"thread_id": THREAD_ID}}

        print(f"Task: {task}\n")
        print("=== Streaming events ===\n")

        event_count = 0
        for namespace, mode, chunk in agent.stream(
            {"messages": [{"role": "user", "content": task}]},
            config=config,
            stream_mode=["updates", "messages"],
            subgraphs=True,
        ):
            event_count += 1
            label = label_for(namespace, mode)

            if mode == "messages":
                message_chunk, metadata = chunk
                text = getattr(message_chunk, "content", "")
                if text:
                    print(f"{label} token: {text!r}")

            elif mode == "updates":
                for node_name, node_output in chunk.items():
                    print(f"{label} node '{node_name}' updated")
                    if isinstance(node_output, dict) and "messages" in node_output:
                        for m in node_output["messages"]:
                            role = getattr(m, "type", "unknown")
                            content_preview = str(getattr(m, "content", ""))[:80]
                            tool_calls = getattr(m, "tool_calls", None)
                            if tool_calls:
                                for tc in tool_calls:
                                    print(f"    -> tool call: {tc.get('name')}({tc.get('args')})")
                            elif content_preview:
                                print(f"    -> {role}: {content_preview}")

        print(f"\n=== Done. {event_count} raw stream events received. ===")

        state = agent.get_state(config)
        if state.next:
            print(f"\nPaused — awaiting approval for: {state.next}")
        else:
            print("\nCompleted, no pending interrupt.")


if __name__ == "__main__":
    main()
