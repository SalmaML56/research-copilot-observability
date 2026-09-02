# LangChain Layer Stack (bottom to top)

1. LangGraph — engine: state, checkpoints, streaming.
2. create_agent — thin agent loop on top of LangGraph.
3. Deep Agents — adds planning, virtual filesystem, subagents, skills.

This project builds on Deep Agents: we need planning + researcher/writer
subagent split + shared notes between them (virtual filesystem is exactly
for that). Building this by hand at a lower layer would mean re-implementing
what Deep Agents already provides.
