"""
Tools available to the agents.

Step 18 follow-up fix (Finding 3): when web_search exhausts its retries
and returns a failure string, we now explicitly mark that span as a
Langfuse WARNING instead of letting it default to plain "success".

Phase 5, P5-02: the Langfuse `@observe` decorator is now applied through
`observe_if_langfuse`, which makes it a no-op unless TRACING_BACKEND asks
for Langfuse. Previously it was unconditional, and because Langfuse v4
attaches its own span processor to the global TracerProvider, every tool
call was exported twice - 74 `web_search` spans for 37 real HTTP calls.
Any Phase 5 tool-call count, error rate, or latency panel was 2x wrong.

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

import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from ddgs import DDGS
from ddgs.exceptions import DDGSException
from langchain_core.tools import tool
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from research_copilot.observability.tracing_mode import (
    observe_if_langfuse,
    update_langfuse_span,
)

# Step 18 fix (Finding: unbounded search hang): DDGS's own timeout=5 default
# is NOT reliably enforced in this network environment — observed via py-spy
# that a search call can block for 5+ minutes with no exception raised,
# hanging the entire agent run. We enforce our own hard wall-clock timeout
# on a dedicated thread pool, independent of what DDGS/its HTTP backend do
# internally.
_search_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="web_search_hard_timeout")
# Tightened after live testing in this environment: search engine reachability
# is unreliable here, so a subagent making several search calls (each with a
# hard timeout + retries) could accumulate several minutes of wait even though
# no single call hangs forever. Lower per-call timeout and fewer retries keep
# worst-case-per-query time low, since we already have a partial-failure
# fallback message for callers.
_SEARCH_HARD_TIMEOUT_SECONDS = 8
_SEARCH_MAX_ATTEMPTS = 2

tracer = trace.get_tracer("research_copilot.tools")
log = logging.getLogger("research_copilot.tools")


@tool
@observe_if_langfuse(as_type="tool")
def web_search(query: str, max_results: int = 5) -> str:
    """
    Search the web and return a summary of results (titles, snippets, URLs)
    for the given query.
    """
    last_error: Exception | None = None

    for attempt in range(_SEARCH_MAX_ATTEMPTS):
        with tracer.start_as_current_span("web_search.ddgs_http_call") as span:
            span.set_attribute("gen_ai.tool.name", "web_search")
            span.set_attribute("web_search.attempt", attempt + 1)
            span.set_attribute("web_search.query", query)
            try:
                future = _search_executor.submit(DDGS().text, query, max_results=max_results)
                try:
                    results = future.result(timeout=_SEARCH_HARD_TIMEOUT_SECONDS)
                except FutureTimeoutError as e:
                    raise DDGSException(
                        f"Search hard-timed-out after {_SEARCH_HARD_TIMEOUT_SECONDS}s "
                        f"(DDGS's own timeout was not honored by the network/HTTP backend)"
                    ) from e

                span.set_attribute("web_search.result_count", len(results) if results else 0)

                if not results:
                    raise DDGSException("No results found.")

                formatted = "\n\n".join(
                    f"Title: {r.get('title', '')}\n"
                    f"URL: {r.get('href', '')}\n"
                    f"Snippet: {r.get('body', '')}"
                    for r in results
                )
                span.set_status(Status(StatusCode.OK))
                return formatted or "No results found."

            except DDGSException as e:
                last_error = e
                span.set_attribute("web_search.failed", True)
                span.record_exception(e)
                # Review v2, Step 24: failed attempts used to be left UNSET.
                # 78 spans UNSET / 0 ERROR in a real trace meant any
                # tool-failure-rate alert (Step 36c) read 0% forever.
                span.set_status(Status(StatusCode.ERROR, str(e)))
                if attempt < _SEARCH_MAX_ATTEMPTS - 1:
                    time.sleep(2 * (attempt + 1))
                    continue

    update_langfuse_span(
        level="WARNING",
        status_message=f"web_search exhausted retries: {last_error}",
    )
    # Step 37: this is the log line an on-call person lands on from a red
    # tool-error panel. It carries trace_id/session_id automatically via the
    # logging_setup formatter + IdentityFilter, so the trace is one click away.
    log.warning(
        "web_search exhausted retries",
        extra={
            "gen_ai.tool.name": "web_search",
            "web_search.query": query,
            "web_search.attempts": _SEARCH_MAX_ATTEMPTS,
            "error": str(last_error),
        },
    )

    return (
        f"Search failed after retries for query '{query}': {last_error}. "
        "This is often a temporary block on cloud IPs — try a more specific "
        "or differently worded query."
    )


@tool
@observe_if_langfuse(as_type="tool")
def finalize_report(report_text: str) -> str:
    """
    Marks the final report as ready for publication. This is the LAST step
    in the workflow — call this only once the writer subagent has produced
    a complete final report and you are ready to submit it.

    Step 10 (human-in-the-loop): this tool requires human approval before
    it actually executes — the agent will pause here until approved.
    """
    return f"Report finalized and published ({len(report_text)} characters)."
