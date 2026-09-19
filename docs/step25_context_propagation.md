# Step 25 - Context Propagation, Repeated with the Real Researcher Subagent

Per the review action plan, this exercise had two gaps:
1. The demo used plain synthetic spans instead of a real subagent.
2. The doc incorrectly implied asyncio.create_task has the same
   context-loss problem as threading.Thread.

Both are fixed in context_propagation_demo.py.

## Fix 1 - Real subagent, stub model

The demo now builds the actual create_deep_agent() graph using the
project's real researcher subagent config
(research_copilot.agents.subagents.researcher), with a stub
FakeMessagesListChatModel standing in for the real LLM (per review
guidance: "fake/stub model OK for this check"). This makes zero real API
calls while still exercising the genuine LangGraph/deepagents subagent
delegation path (task tool call, subagent invocation, subagent's own
model call, final answer), not a hand-rolled synthetic span tree.

## Fix 2 - Corrected the asyncio.create_task claim

The original docstring implied asyncio.create_task needed the same
manual context-copying as threading.Thread. This is incorrect: since
Python 3.7, asyncio automatically copies the current contextvars.Context
into every new Task - this has always been true and is not specific to
Python 3.11. The docstring now states this correctly and clarifies the
propagation gap is specific to threading.Thread (and any other mechanism
that hands work to a new OS thread), not to asyncio tasks.

## Evidence (fresh run, real subagent graph)

BROKEN (plain threading.Thread, no context handling):
parent trace_id: 425a48c7c7fb9f9fc4c58bb4332892a6
child trace_id:  9c472595a96451a9e9c674370b5646af

Different trace IDs - the subagent's real graph execution split into its
own disconnected trace, exactly as the broken pattern predicts.

FIXED (context captured and attached before invoking the same real
subagent graph):
parent trace_id: 25b589f33a4212e199d72b5f59fcaa3a
child trace_id:  25b589f33a4212e199d72b5f59fcaa3a

Identical trace IDs - the real subagent's execution correctly continues
the parent trace once context is explicitly attached.

Both runs completed successfully (Answer captured: "Done. Lead agent
final answer."), confirming the stub model correctly drove the real
subagent graph through delegation and back, in both scenarios.

## Note (per review): this does not fix Step 24's identity gap

Fixing trace linkage (parent/child trace ID matching) is a separate
mechanism from propagating identity attributes (session_id, user_id,
etc. - Steps 5/24's IdentitySpanProcessor). This demo only demonstrates
and fixes the trace-ID-splitting problem; it does not by itself restore
identity attributes on a subagent thread's spans. That remains the
IdentitySpanProcessor's job and is unaffected by this fix.
