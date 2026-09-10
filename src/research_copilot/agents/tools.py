"""
Tools available to the agents.

Step 18 follow-up fix (Finding 3): when web_search exhausts its retries
and returns a failure string, we now explicitly mark that span as a
Langfuse WARNING instead of letting it default to plain "success".

Phase 3, step 24: the @tool/@observe decorators auto-trace the tool CALL
itself, but the actual outbound HTTP request made by DDGS().text() inside
ddgs is invisible to OpenInference/OpenLLMetry's auto-instrumentation —
ddgs isn't an OTel-aware library. We add a manual OTel span around that
specific call, tagged with gen_ai.tool.name per the Phase 0 trace
contract, so that detail isn't lost.

Note: session_id/user_id (also part of the trace contract) are NOT
threaded into this manual span — they live in the LangChain invoke
config's metadata, not in scope inside this function. Propagating them
into manually-created spans deep inside tool code is exactly what Step 25
digs into next.
"""

import time
from ddgs import DDGS
from ddgs.exceptions import DDGSException
from langchain_core.tools import tool
from langfuse import get_client, observe
from opentelemetry import trace

tracer = trace.get_tracer("research_copilot.tools")


@tool
@observe(as_type="tool")
def web_search(query: str, max_results: int = 5) -> str:
    """
    Search the web and return a summary of results (titles, snippets, URLs)
    for the given query.
    """
    last_error: Exception | None = None

    for attempt in range(3):
        with tracer.start_as_current_span("web_search.ddgs_http_call") as span:
            span.set_attribute("gen_ai.tool.name", "web_search")
            span.set_attribute("web_search.attempt", attempt + 1)
            span.set_attribute("web_search.query", query)
            try:
                results = DDGS().text(query, max_results=max_results)
                span.set_attribute("web_search.result_count", len(results) if results else 0)

                if not results:
                    raise DDGSException("No results found.")

                formatted = "\n\n".join(
                    f"Title: {r.get('title', '')}\n"
                    f"URL: {r.get('href', '')}\n"
                    f"Snippet: {r.get('body', '')}"
                    for r in results
                )
                return formatted or "No results found."

            except DDGSException as e:
                last_error = e
                span.set_attribute("web_search.failed", True)
                span.record_exception(e)
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))
                    continue

    try:
        get_client().update_current_span(
            level="WARNING",
            status_message=f"web_search exhausted retries: {last_error}",
        )
    except Exception:
        pass

    return (
        f"Search failed after retries for query '{query}': {last_error}. "
        "This is often a temporary block on cloud IPs — try a more specific "
        "or differently worded query."
    )


@tool
@observe(as_type="tool")
def finalize_report(report_text: str) -> str:
    """
    Marks the final report as ready for publication. This is the LAST step
    in the workflow — call this only once the writer subagent has produced
    a complete final report and you are ready to submit it.

    Step 10 (human-in-the-loop): this tool requires human approval before
    it actually executes — the agent will pause here until approved.
    """
    return f"Report finalized and published ({len(report_text)} characters)."
