"""
Tools available to the agents. Currently just web_search, used by the
researcher subagent.
"""

import time
from ddgs import DDGS
from ddgs.exceptions import DDGSException
from langchain_core.tools import tool


@tool
def web_search(query: str, max_results: int = 5) -> str:
    """
    Search the web and return a summary of results (titles, snippets, URLs)
    for the given query.

    Retries a few times with backoff because DuckDuckGo occasionally rate
    limits or returns "No results found" for requests coming from cloud /
    datacenter IPs (e.g. GitHub Codespaces) — this is usually transient,
    not a real absence of results.
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
                time.sleep(2 * (attempt + 1))  # 2s, then 4s backoff
                continue

    return (
        f"Search failed after retries for query '{query}': {last_error}. "
        "This is often a temporary block on cloud IPs — try a more specific "
        "or differently worded query, or note in your notes file that this "
        "subtopic could not be searched."
    )
