# Step 28 - Langfuse vs Phoenix, Genuine Same-Run Comparison

Per the review: the previous comparison called the same prompt twice
independently (once per backend), which does not guarantee identical
execution. This run exports ONE single agent invocation to both
destinations SIMULTANEOUSLY, via two BatchSpanProcessors on the same
TracerProvider - guaranteeing a literally identical trace ID at both
backends, from one real execution.

Script: run_step28_same_run_comparison.py

## Setup

One TracerProvider, one OpenInference instrumentation pass, two exporters:
- Phoenix: http://localhost:6006/v1/traces (no auth)
- Langfuse: {LANGFUSE_HOST}/api/public/otel/v1/traces (HTTP Basic auth)

Task: "What is a small modular nuclear reactor? Answer in 2 sentences, no research needed."

## Result: same trace ID confirmed in both

Trace ID: 3afbd5923551df8f947b67b36a859c9b

Confirmed present in Phoenix (GraphQL API, spans query) AND in Langfuse
(Observations API v2, trace_id filter) - both returned the exact same
trace ID with matching span names (model, ChatDeepSeek, LangGraph,
TodoListMiddleware.after_model, PatchToolCallsMiddleware.before_agent,
plus our own manual step28.same_run_root span).

## Key finding: model-span cost/usage differs between the two backends

Per review guidance to specifically inspect a model span with nonzero
token usage (not a zero-cost tool span) - this is exactly where a real
difference showed up.

**Phoenix - ChatDeepSeek span, real usage data present:**
token_usage: completion_tokens=102, prompt_tokens=4476, total_tokens=4578
usage_metadata: input_tokens=4476, output_tokens=102
(Full request/response JSON also present, matching what we saw in
Step 22's OpenInference investigation.)

**Langfuse - same trace ID, same ChatDeepSeek observation:**
input: None
output: None
usage_details: None
cost_details: None
total_cost: None
(Only structural fields - type=GENERATION, correct parent_observation_id,
correct trace_id, latency=1.39s - were populated correctly.)

## Interpretation

This is a real, previously-unverified gap, distinct from Step 26's
session_id/user_id finding but in the same family: Langfuse's OTLP
ingestion correctly captures span structure and timing from
OpenInference-instrumented spans, but does NOT populate input/output/
usage/cost fields on GENERATION-type observations from OpenInference's
attribute names (input.value/output.value/gen_ai.usage.*). Phoenix does
populate all of this correctly from the exact same span data.

This means: for the direct-OTel-to-Langfuse path specifically, cost/usage
dashboards in Langfuse would show nothing for model calls, even though
the traces themselves look structurally complete. Phoenix is not affected.

This does not affect the main FastAPI app's primary observability path
(OTel Collector -> Grafana/Tempo, and separately the Langfuse
CallbackHandler path used in main_agent.py, which is a different
ingestion mechanism from direct OTLP export and was not tested here).

## Action / recommendation

Not fixed in this pass (flagged, not silently left for rediscovery): if
direct-OTel-to-Langfuse export is used for cost tracking, either (a)
verify with Langfuse support/docs the exact attribute names their OTLP
GENERATION mapping expects for input/output/usage (possibly OpenLLMetry's
naming convention rather than OpenInference's, based on the pattern found
in Step 26), or (b) rely on the Langfuse CallbackHandler path
(main_agent.py) for cost-sensitive workflows instead, since that path
uses Langfuse's own native SDK integration rather than generic OTLP.
