"""Step 50: push the agent system prompts from code to Langfuse prompt
management (plan Q6: code is the source of truth, Langfuse keeps the
numbered history).

    uv run python scripts/phase8/sync_prompts.py           # sync
    uv run python scripts/phase8/sync_prompts.py --check   # exit 1 if out of sync, 2 if unreachable

A new Langfuse version is created only when the code text differs from the
current `production` version, and it takes the `production` label, so
re-running without a prompt change is a no-op. Run it after merging a
prompt change; until then the running agent stamps local-<hash> versions
(see agents/prompt_registry.py).
"""

import subprocess
import sys

from dotenv import load_dotenv

load_dotenv()

from langfuse import get_client  # noqa: E402

from research_copilot.agents.prompt_registry import LABEL, PROMPTS, _fetch_versions  # noqa: E402


def git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def main() -> int:
    check_only = "--check" in sys.argv[1:]
    try:
        current = _fetch_versions(raise_errors=True)
    except Exception as e:
        print(f"Cannot read prompts from Langfuse ({type(e).__name__}: {e}) - nothing checked or synced.")
        return 2

    out_of_sync = 0
    for role, (name, text) in PROMPTS.items():
        remote = current.get(role)
        if remote and remote.get("prompt") == text:
            print(f"{name}: in sync ({LABEL} = version {remote['version']})")
            continue
        out_of_sync += 1
        was = f"version {remote['version']}" if remote else "missing"
        if check_only:
            print(f"{name}: OUT OF SYNC ({LABEL} is {was})")
            continue
        created = get_client().create_prompt(
            name=name,
            prompt=text,
            labels=[LABEL],
            type="text",
            commit_message=f"sync from git {git_commit()}",
        )
        print(f"{name}: created version {created.version} (was {was})")

    if not check_only:
        get_client().flush()
    return 1 if check_only and out_of_sync else 0


if __name__ == "__main__":
    sys.exit(main())
