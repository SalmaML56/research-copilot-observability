# Phase 5 design decisions (Steps 35 and 37)

Two things the task list flagged as "decide before building". Written down
here rather than left implicit in a panel query.

---

## P5-32 — how "subagent depth" is measured

**Decision: count the named delegation spans, do not compute span-tree
depth in the Collector.**

The dashboard panel *Subagent depth (delegation calls per minute, by
level)* plots `traces_span_metrics_calls_total` filtered to
`span_name =~ "LangGraph|task|researcher|writer|model"`.

### Why not compute real tree depth

The obvious alternative is to derive a `depth` attribute from the span
parent chain. Two problems:

1. The OTel Collector processes spans in batches and does not guarantee
   that a parent has been seen before its child. Computing depth there
   means buffering a whole trace, which the `span_metrics` connector is not
   built to do.
2. Doing it in the app means every span-creating library would have to
   cooperate — OpenInference creates most of our spans and knows nothing
   about our delegation model.

### Why counting named levels is equivalent here

The delegation shape in this project is fixed:

```
POST /research  ->  LangGraph  ->  task  ->  researcher | writer  ->  model  ->  ChatDeepSeek
```

Each name appears at exactly one depth. Counting spans per name therefore
gives the same information as a tree walk, with no extra moving parts.
Verified against the live trace: `LangGraph` 2.51/min, `model` 40.9/min,
`researcher` 2.78/min, `task` 3.79/min, `writer` 1.01/min — the pyramid you
would expect.

### When this stops being true

**If the graph ever gains variable-depth delegation — a subagent that can
spawn another subagent of the same kind — this panel becomes wrong and
must be replaced by real depth computation.** Recorded here so the next
person does not inherit a silently-misleading panel.

---

## P5-54 — what must never be logged

**Decision: log identifiers and outcomes. Never log prompt text, model
output, retrieved documents, or search result bodies.**

Phase 7's Step 45 formalises content capture across the whole pipeline.
This is the narrower question for Step 37's logs, settled now because the
logging code is being written now.

### What the logger emits

Every record carries: timestamp, level, logger, message, `service.name`,
`trace_id`, `span_id`, `trace_flags`, `session_id`, `user_id`,
`environment`, `prompt_version`.

Explicit `extra` fields currently in use:

| Field | Where | Why it is safe |
|---|---|---|
| `topic` | `research request received` | The user's own one-line request. Already the primary key of the run, and visible in the trace. |
| `gen_ai.tool.name` | tool failure | Tool identifier, not content |
| `web_search.query` | tool failure | The query string, not the results |
| `web_search.attempts` | tool failure | A count |
| `error` | tool failure | The exception message |

### What is deliberately absent

- Chat messages, system prompts, and model completions.
- Web search result bodies.
- File contents read or written by the agent's virtual filesystem.

Those already live on spans, where OpenInference captures them and where
Step 45's capture switch will be able to turn them off in one place. Having
a second, uncontrolled copy in the log stream would mean Step 45 could
switch off content capture and quietly leave it all in Loki.

### The one field worth revisiting

`topic` is user-supplied free text. It is logged because a run is almost
unusable to debug without knowing what was asked, and it is the same string
that already appears on the root span. If this system ever takes untrusted
user input, `topic` should move behind the Step 45 capture switch along
with everything else.

### Log volume note

`LOG_LEVEL` defaults to `INFO`. The HTTP client library used by DeepSeek
logs one `HTTP Request: POST .../chat/completions "HTTP/1.1 200 OK"` line
per model call at INFO — 19 lines for one run in the captured evidence.
That is useful for correlating latency, but it is the first thing to raise
to WARNING if log volume ever becomes a cost problem.
