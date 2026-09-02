# Trace vs Span

- **Trace** = the whole story of one request, start to finish. One `trace_id`.
- **Span** = one single operation inside that story (one LLM call, one tool call).
  Spans nest — a span can have child spans.

## Sketch: one hypothetical Research Copilot run

TRACE: user asks "summarize latest AI safety research"
├── SPAN: agent.plan
├── SPAN: agent.researcher.run
│     ├── SPAN: tool.web_search
│     ├── SPAN: llm.call
│     └── SPAN: tool.file_write
├── SPAN: agent.writer.run
│     ├── SPAN: tool.file_read
│     └── SPAN: llm.call
└── SPAN: agent.final_answer

All spans share one trace_id; each has its own span_id + parent_span_id,
which lets Langfuse/Phoenix/Grafana draw this tree automatically.
