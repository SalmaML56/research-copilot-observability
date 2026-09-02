"""
Central place to read configuration/environment variables from.

Why this file exists: every other module should import settings from HERE,
never call os.environ directly. That way, if we later need to validate a
value, rename an env var, or add a default, we change it in one place instead
of hunting through the whole codebase.
"""

import os
from dotenv import load_dotenv

# Loads variables from a local .env file (if present) into the process
# environment. In Codespaces/CI, real env vars set outside .env also work —
# load_dotenv() does not override variables that are already set.
load_dotenv()


class Settings:
    # Which environment this process is running in. Gets stamped onto every
    # span per the trace contract (docs/trace-contract.md).
    environment: str = os.getenv("ENVIRONMENT", "dev")

    # Groq is our chosen model provider — genuinely free tier, no credit
    # card, rate-limited (not a trial credit that runs out).
    groq_api_key: str | None = os.getenv("GROQ_API_KEY")

    # Which Groq-hosted model the main agent uses by default. Kept as a
    # setting (not hardcoded in agent code) so we can swap models per
    # environment without touching agent logic.
    default_model: str = os.getenv("DEFAULT_MODEL", "groq:openai/gpt-oss-120b")

    def validate(self) -> None:
        """
        Fail loudly and early if a required secret is missing, instead of
        letting the agent fail deep inside a LangGraph call with a confusing
        stack trace.
        """
        if not self.groq_api_key:
            raise RuntimeError(
                "GROQ_API_KEY is not set. Copy .env.example to .env "
                "and fill in your key before running any agent code."
            )


settings = Settings()
