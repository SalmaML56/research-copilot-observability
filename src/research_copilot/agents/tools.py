"""
Web search tool for our agents.

Uses `ddgs` (DuckDuckGo Search) instead of a paid API like Tavily/SerpAPI —
deliberately, so this project runs with zero extra signups or API keys for
search. If result quality becomes a problem later (Phase 6 evals will surface
this objectively via correctness scores), swapping to Tavily is a ~10-line
change confined to this one file.
"""

from ddgs import DDGS
from langchain_core.tools import tool


@tool
def web_search(query: str, max_results: int = 5) -> str:
    """
    Search the web for a query and return the top results as plain text.

    Args:
        query: What to search for.
        max_results: How many results to return (default 5, keep this low —
            more results means more tokens fed back into the LLM's context).

    Returns:
        A newline-separated list of "title: snippet (url)" strings, or a
        message saying no results were found.
    """
    results = DDGS().text(query, max_results=max_results)

    if not results:
        return f"No search results found for query: {query!r}"

    lines = []
    for r in results:
        title = r.get("title", "").strip()
        body = r.get("body", "").strip()
        href = r.get("href", "").strip()
        lines.append(f"{title}: {body} ({href})")

    return "\n".join(lines)
