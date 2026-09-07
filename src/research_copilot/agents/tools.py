"""
Tools available to the agents.

Phase 2, step 17: both tools are wrapped with Langfuse's @observe decorator
(as_type="tool") so they appear as explicit tool-type spans in Langfuse,
with their real inputs/outputs captured — not just as generic function
calls inferred from the LangChain callback handler alone. Verified that
@observe placed under @tool preserves LangChain's schema introspection
(tool.name, .description, .args all still correct).
"""

import time
from ddgs import DDGS
from ddgs.exceptions import DDGSException
from langchain_core.tools import tool
from langfuse import observe


@tool
@observe(as_type="tool")
def web_search(query: str, max_results: int = 5) -> str:
    """
    Search the web and return a summary of results (titles, snippets, URLs)
    for the given query.
    """
    last_error: Exception | None = None

    for attempt in range(3):
        try:
            results = DDGS().text(query, max_results=max_results)
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
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue

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
