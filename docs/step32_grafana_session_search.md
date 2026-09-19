# Step 32 — Find a Run in Grafana by Session ID (Fresh Evidence)

Per the review action plan: "run the demo fresh, actually find the session
via TraceQL in the current instance, save that as current evidence." The
mechanism itself (session_id tagged on spans, TraceQL query) was already
confirmed correct in a prior review pass, but the evidence was stale (an
old demo run that could no longer be found in the current Tempo store).

## What was done

1. Added session identity to run_otel_demo.py (it previously ran with no
   set_identity() call at all, confirmed via an empty TraceQL search
   before making this change - it returned zero traces).
2. Ran the demo fresh with session ID step32-grafana-search-<random> set
   via set_identity() before the agent invocation.
3. Queried Tempo two ways: directly via its search API and visually
   confirmed in the Grafana Explore UI using the same TraceQL query.

## Evidence

Query used (both terminal and Grafana UI):
{ span.session_id =~ "step32-grafana-search-.*" }

Result: 20 traces found, all with service research-copilot-agent, spanning
the full delegation chain for this one run: finalize_report, LangGraph
(1.27 min, the root delegation span), and multiple web_search tool calls
(2.4s to 8.3s each) - confirming the session tag correctly links spans
across lead agent, tools, and subagent calls, and that a fresh run can be
found by session ID in the current Tempo instance, not a stale prior one.

Confirmed two ways:
1. Terminal: docker exec grafana-lgtm curl against the Tempo search API -
   20 results returned as JSON.
2. Grafana UI (Explore -> Tempo -> TraceQL): same query, same 20 traces,
   visually confirmed in the Table view with trace IDs, start times,
   service names, span names, and durations all visible.

Example trace IDs: 4f0f684da66cec377985e1f61bd68b0c (finalize_report),
64b9752887e46fe8caae51b (LangGraph, 1.27 min), 30d00e0257d4c6e5e28747
(web_search, 8.28s).

## Conclusion

Session-based search in Grafana/Tempo works correctly against the current
running instance, verified both programmatically and visually.
run_otel_demo.py now sets identity by default, so this remains verifiable
going forward without needing a separate one-off patch each time.
