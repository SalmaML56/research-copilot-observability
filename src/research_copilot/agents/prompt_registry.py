"""
Phase 8, Step 50: prompt versions from Langfuse prompt management, stamped
on every trace as `prompt_version`.

Plan Q6: the prompt TEXT lives in code (agents/subagents.py) and goes
through review and the Step 49 eval gate like any other change.
scripts/phase8/sync_prompts.py pushes it to Langfuse, which numbers the
versions and keeps the history. At runtime the agent always runs the code
text; Langfuse is only asked "which version number is this exact text?".

The stamp therefore never claims a version that did not run:
  lead=3,researcher=1,writer=2       Langfuse's `production` text is
                                     identical to the code text
  lead=local-1a2b3c4d,...            not synced, Langfuse unreachable, or
                                     not configured (CI) - a hash of the
                                     code text, so it is still exact

Why a raw REST call instead of langfuse.get_client(): constructing the SDK
client attaches a LangfuseSpanProcessor to the global TracerProvider
(langfuse/_client/resource_manager.py), which is the exact double-export
Phase 5 P5-02 removed for TRACING_BACKEND=otel. The client is also a
per-public-key singleton, so building one here with tracing disabled would
silently change it for api/main.py's create_score calls too.
"""

import functools
import hashlib
import logging
import os
from urllib.parse import quote

import httpx

from research_copilot.agents.subagents import LEAD_AGENT_SYSTEM_PROMPT, researcher, writer

logger = logging.getLogger(__name__)

# Plan Q8: the three agent system prompts only. The judge criteria stay in
# git, since changing them changes how scores are computed.
PROMPTS = {
    "lead": ("research-copilot-lead", LEAD_AGENT_SYSTEM_PROMPT),
    "researcher": ("research-copilot-researcher", researcher["system_prompt"]),
    "writer": ("research-copilot-writer", writer["system_prompt"]),
}
LABEL = "production"
FETCH_TIMEOUT_SECONDS = 3.0


def local_version(text: str) -> str:
    return "local-" + hashlib.sha256(text.encode()).hexdigest()[:8]


def _is_prompt_not_found(response: httpx.Response) -> bool:
    try:
        return response.json().get("error") == "LangfuseNotFoundError"
    except ValueError:
        return False


def _fetch_versions(raise_errors: bool = False) -> dict[str, dict]:
    """{role: {"version": int, "prompt": str}} for every prompt Langfuse has
    under LABEL. Empty when Langfuse isn't configured or can't be reached -
    unless raise_errors, which sync_prompts.py uses so an unreachable
    Langfuse isn't reported as "every prompt is missing" (seen live)."""
    host = os.getenv("LANGFUSE_HOST") or os.getenv("LANGFUSE_BASE_URL")
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    if not (host and public_key and secret_key):
        if raise_errors:
            raise RuntimeError("LANGFUSE_HOST/PUBLIC_KEY/SECRET_KEY are not all set")
        return {}
    found: dict[str, dict] = {}
    try:
        with httpx.Client(
            base_url=host, auth=(public_key, secret_key), timeout=FETCH_TIMEOUT_SECONDS
        ) as client:
            for role, (name, _) in PROMPTS.items():
                # The first names were "research-copilot/lead" etc. An
                # unencoded "/" misses the API route and Langfuse's web app
                # answers with its HTML 404 page, which this used to read as
                # "prompt not found" - so every sync re-created every prompt
                # (seen live). The SDK's prompts.delete doesn't encode it
                # either, hence the dash names. Still encode, and only treat
                # Langfuse's own JSON not-found as "missing".
                response = client.get(
                    f"/api/public/v2/prompts/{quote(name, safe='')}", params={"label": LABEL}
                )
                if response.status_code == 404 and _is_prompt_not_found(response):
                    continue
                response.raise_for_status()
                found[role] = response.json()
    except httpx.HTTPError as e:
        if raise_errors:
            raise
        logger.warning("Langfuse prompt lookup failed, stamping local hashes: %s", e)
    return found


@functools.cache
def prompt_versions() -> dict[str, str]:
    fetched = _fetch_versions()
    versions = {}
    for role, (name, text) in PROMPTS.items():
        remote = fetched.get(role)
        if remote and remote.get("prompt") == text:
            versions[role] = str(remote["version"])
            continue
        if remote:
            logger.warning(
                "Prompt %s differs from Langfuse %s version %s - run "
                "scripts/phase8/sync_prompts.py. Stamping the local hash.",
                name, LABEL, remote.get("version"),
            )
        versions[role] = local_version(text)
    return versions


def prompt_version_stamp() -> str:
    return ",".join(f"{role}={version}" for role, version in prompt_versions().items())
