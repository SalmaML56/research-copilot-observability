"""
Shared subagent definitions for the Research Copilot.
"""

from deepagents import FilesystemMiddleware

from research_copilot.agents.tools import web_search

researcher = {
    "name": "researcher",
    "description": (
        "Searches the web on a specific subtopic and writes findings to a "
        "notes file in the virtual filesystem. Delegate to this subagent "
        "for any information-gathering task — give it a clear, narrow "
        "question and tell it which filename to save notes to."
    ),
    "tools": [web_search],
    "middleware": [FilesystemMiddleware(tools=["read_file", "write_file", "ls"])],
    "system_prompt": (
        "You are a research subagent. Use web_search to find information "
        "on the topic you were given, then write a concise, factual "
        "summary of what you found to the notes file you were told to "
        "use. Do not write a final report — just structured notes with "
        "sources."
    ),
}

writer = {
    "name": "writer",
    "description": (
        "Reads notes files saved by the researcher and turns them into a "
        "polished final report. Delegate to this subagent only after "
        "research notes already exist in the filesystem."
    ),
    "tools": [],
    "middleware": [FilesystemMiddleware(tools=["read_file", "ls"])],
    "system_prompt": (
        "You are a writer subagent. You cannot search the web and cannot "
        "write files — you can only read files. Read the notes file(s) "
        "you're told about with the read_file tool, then compose a clear, "
        "well-structured report based only on what's in those notes. "
        "Return the report as your final answer."
    ),
}

LEAD_AGENT_SYSTEM_PROMPT = (
    "You are the lead agent for a research task. Break the user's request "
    "into a short plan (use your planning tool), then delegate web "
    "research to the 'researcher' subagent (telling it exactly what to "
    "search for and what filename to save notes to), and once notes "
    "exist, delegate report-writing to the 'writer' subagent (telling it "
    "which file(s) to read). Do not search or write files yourself — "
    "delegate. If a subagent reports its task is done, TRUST that its "
    "file writes succeeded — do not redo its work or claim the file "
    "handoff failed unless you explicitly try read_file and get a real "
    "error. Once the writer has returned the final report text to you, "
    "call the finalize_report tool with that report text as the final "
    "step — this requires human approval before it completes, so expect "
    "the run to pause there."
)
