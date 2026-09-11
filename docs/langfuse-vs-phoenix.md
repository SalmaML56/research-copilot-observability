# Phase 4, Step 28 — Langfuse vs Phoenix Comparison

Same agent run (Eiffel Tower research task) sent to both Langfuse and
Phoenix, reviewed side by side.

## Subagent grouping

Langfuse: default trace view immediately shows a nested tree — lead
agent, researcher, writer, each tool call as indented children, readable
at a glance.

Phoenix: default view is a flat, filterable/sortable table. Hierarchy
exists (expand arrows), but isn't the first thing you see — Phoenix
optimizes for searching across many traces; Langfuse optimizes for
reading one trace's story top to bottom.

## Cost visibility

Langfuse: token/cost totals visible directly on the Sessions list without
opening anything.

Phoenix: a "Total Cost" field exists per span (confirmed $0 on the
web_search tool span — expected, tools don't consume LLM tokens; cost
only accrues on LLM-type spans). Getting a project-wide total requires
navigating to the right span type — less immediate than Langfuse's
default.

## Real finding: attribute naming leak

Every backend receiving our traces sees web_search's tool span tagged
with Langfuse-specific attribute names — langfuse.observation.type,
langfuse.observation.input, langfuse.observation.output — confirmed
directly in Phoenix's UI, a completely different product. This happens
because tools.py decorates web_search with Langfuse's own
@observe(as_type="tool") (added in Step 17), which writes
Langfuse-namespaced attributes onto the active span regardless of which
backend receives it.

This is a small crack in Phase 3's "vendor-neutral" goal — worth
revisiting later: either drop @observe in favor of pure OTel manual spans
(Step 24's pattern), or accept this as a documented inconsistency
specific to tool-level spans.

## Eval tooling

Phoenix: dedicated, first-class sidebar nav — "Datasets & Experiments"
and "Evaluators" — positioned as primary features.

Langfuse: also supports evaluations/datasets, but a similarly prominent
top-level nav item wasn't observed during this project's actual usage so
far.

## Summary

Neither tool is strictly better — they optimize for different things.
Langfuse felt faster for at-a-glance single-run understanding and cost;
Phoenix felt built for searching across many runs, with evaluation
workflows built in as a primary feature (relevant for Phase 6). The
attribute-naming leak is the most concrete, actionable finding — a real
inconsistency from our own code, not a platform limitation.
