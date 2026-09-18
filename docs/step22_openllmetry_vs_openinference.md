# Step 22 — OpenInference vs OpenLLMetry: Real Comparison

Per the review action plan: "run both instrumentors on a task that exercises
researcher, writer, and tools; save the tree-shape/attribute comparison as
an artifact." Previous attempt used a trivial no-research prompt; this run
uses a real research task that exercises the full delegation chain.

**Task used (identical for both):** "Research the CAP theorem in distributed
systems and write a short summary."

Each instrumentor was run in a **separate process** (`run_otel_demo.py` for
OpenInference, `run_openllmetry_demo.py` for OpenLLMetry) per the existing
warning in both files' docstrings — both instrumentors patch LangChain's
internals, so running them together in one process would corrupt the
comparison.

## Quantitative: span count

| Instrumentor | Total spans emitted | Run time |
|---|---|---|
| OpenInference | 297 | 3m17s |
| OpenLLMetry | 559 | 2m27s |

OpenLLMetry produced **~1.9x more spans** for the same task. This is not
noise — see the naming breakdown below.

## Span naming and tree structure

**OpenInference** names spans by the LangChain/tool component itself, flat:
`web_search` (66), `tools` (55), `web_search.ddgs_http_call` (49, our own
manual spans), `model` (35), `ChatDeepSeek` (35), `TodoListMiddleware.after_model`
(13), `SummarizationMiddleware.before_model` (13), `read_file` (8), `ls` (5),
`researcher`/`writer` (2/1, subagent delegation), `LangGraph` (1),
`finalize_report` (2).

**OpenLLMetry** names spans with an operation-type prefix on top of the
component name, giving finer lifecycle granularity:
- `execute_task <Middleware>.before_model` / `.after_model` — **every**
  middleware hook (PatchToolCallsMiddleware, FilesystemMiddleware,
  AnthropicPromptCachingMiddleware, SummarizationMiddleware,
  TodoListMiddleware, SubAgentMiddleware, `_DeepAgentsSummarizationMiddleware`)
  gets its own before/after pair as a separate span (38 each for the busiest
  ones) — OpenInference only surfaced 2 of these middleware pairs at all.
- `execute_tool web_search` / `execute_tool write_todos` / `execute_tool
  read_file` / `execute_tool finalize_report` / `execute_tool write_file` —
  tool calls get an `execute_tool` prefix distinct from the tool's own
  internal spans.
- `create_agent researcher` / `create_agent writer` / `create_agent
  general-purpose` **and separately** `invoke_agent researcher` /
  `invoke_agent writer` — OpenLLMetry distinguishes *constructing* a
  subagent from *invoking* it as two different span types; OpenInference
  only recorded `researcher`/`writer` as single spans with no
  construct-vs-invoke distinction.
- `LangGraph.workflow` (vs plain `LangGraph` in OpenInference) and
  `ChatDeepSeek.chat` (vs plain `ChatDeepSeek`).

**Practical effect:** OpenLLMetry's tree shows exactly which middleware
phase (e.g. `SummarizationMiddleware.before_model` vs `.after_model`) a
given chunk of time or an exception belongs to. OpenInference's flatter
tree is easier to read at a glance but can't distinguish "time spent in the
prompt-caching middleware" from "time spent in the model call itself" —
they're both folded into one span.

## Attribute-level differences

Inspected a `ChatDeepSeek` (OpenInference) / `ChatDeepSeek.chat`
(OpenLLMetry) span pair from the same point in the run (the first model
call, deciding to delegate research).

**OpenInference:**
- `Kind: Internal`
- Embeds the **entire raw request/response as JSON blobs**:
  `input.value` (full LangChain message objects, including the complete
  system prompt and **all 9 tool JSON schemas** inline) and `output.value`
  (full LLMResult object). These are large — the system prompt alone runs
  several hundred words, repeated per model-call span.
- Also includes standardized `gen_ai.*` fields (`gen_ai.input.messages`,
  `gen_ai.output.messages`, `gen_ai.usage.input_tokens`,
  `gen_ai.request.model`, `gen_ai.provider.name`) alongside the
  OpenInference-specific `llm.*` fields (`llm.token_count.total`,
  `llm.finish_reason`, `llm.invocation_parameters` — another full copy of
  the tool schemas, `llm.tools.0.tool.json_schema` through `llm.tools.9...`).
- Carries our own `prompt_version` / `environment` identity attributes
  (Step 5 fix) — confirms that fix applies regardless of which
  instrumentor is active.

**OpenLLMetry:**
- `Kind: Client` — marks the span as an outbound network call per OTel
  semantic conventions, which OpenInference's `Internal` does not.
- `gen_ai.input.messages` is present but in a **more compact form** — a
  `role`/`parts` structure without re-embedding the full tool JSON schemas
  inline on every call.

**Interpretation:** OpenInference trades span size for self-containment —
each span is a complete, standalone record of exactly what was sent/received,
useful for exact replay/debugging but expensive (the same ~9-tool schema
gets duplicated across every single model-call span in the trace).
OpenLLMetry trades that self-containment for a *leaner, more standard*
`gen_ai.*`-first payload and a `Kind: Client` classification that's more
semantically correct for what is, mechanically, an HTTP call to an external
API.

## Which to prefer

Neither is strictly better; they serve different needs:

- **OpenInference** is the better fit here for **exact model-call debugging**
  (e.g. Step 30's investigation) — since every span is self-contained, one
  span tells you exactly what was sent and received without needing to
  reconstruct context from sibling spans.
- **OpenLLMetry** is the better fit for **middleware-level performance
  analysis** (e.g. "did SummarizationMiddleware or the model call itself
  cause this latency?") because each middleware hook is its own timed span,
  and the `Kind: Client` tagging is more standards-correct for dashboards
  built on generic OTel span-kind filtering.

This project currently uses OpenInference (`otel_setup.py` /
`setup_otel_instrumentation()`) as the default for the FastAPI app and
Grafana/Phoenix demos; OpenLLMetry remains available as a standalone
comparison script (`run_openllmetry_demo.py`) but is not wired into the
main application path.

## Raw evidence

Full Collector debug-exporter output for both runs (9,164 and 17,681 lines
respectively) captured during this comparison; the counts and span samples
above were extracted directly from those logs with `grep`/`sort`/`uniq -c`,
not estimated.
