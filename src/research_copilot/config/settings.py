"""
Central place to read configuration/environment variables from.

Why this file exists: every other module should import settings from HERE,
never call os.environ directly. That way, if we later need to validate a
value, rename an env var, or add a default, we change it in one place instead
of hunting through the whole codebase.
"""

import os
from dotenv import load_dotenv
from langchain_deepseek import ChatDeepSeek
from langchain_groq import ChatGroq

load_dotenv()


class Settings:
    environment: str = os.getenv("ENVIRONMENT", "dev")

    # --- Primary model: DeepSeek (paid credits, used by default) ---
    deepseek_api_key: str | None = os.getenv("DEEPSEEK_API_KEY")
    primary_model_name: str = os.getenv("DEFAULT_MODEL_NAME", "deepseek-chat")
    max_tokens: int = int(os.getenv("MAX_TOKENS", "4096"))

    # --- Cheap/alternate model: Groq (genuinely free tier, open-weight) ---
    # Step 12: "configure a second, cheaper open-weight model as an
    # alternate harness profile." Groq was already verified working in
    # this project during steps 6-9 before switching to DeepSeek — reusing
    # that integration here rather than adding a 6th provider.
    groq_api_key: str | None = os.getenv("GROQ_API_KEY")
    cheap_model_name: str = os.getenv("CHEAP_MODEL_NAME", "openai/gpt-oss-20b")

    # Which profile is active: "primary" (DeepSeek, paid) or "cheap" (Groq,
    # free). Controlled by env var so switching doesn't require code changes.
    model_profile: str = os.getenv("MODEL_PROFILE", "primary")

    def validate(self) -> None:
        if self.model_profile == "primary" and not self.deepseek_api_key:
            raise RuntimeError(
                "MODEL_PROFILE is 'primary' but DEEPSEEK_API_KEY is not "
                "set. Add it to .env."
            )
        if self.model_profile == "cheap" and not self.groq_api_key:
            raise RuntimeError(
                "MODEL_PROFILE is 'cheap' but GROQ_API_KEY is not set. "
                "Add it to .env."
            )

    def get_primary_model(self) -> ChatDeepSeek:
        """DeepSeek-V3 — the default, paid-credit model."""
        return ChatDeepSeek(
            model=self.primary_model_name,
            api_key=self.deepseek_api_key,
            max_tokens=self.max_tokens,
        )

    def get_cheap_model(self) -> ChatGroq:
        """Groq-hosted open-weight model — free tier, used for cost comparison."""
        return ChatGroq(
            model=self.cheap_model_name,
            api_key=self.groq_api_key,
            max_tokens=self.max_tokens,
        )

    @property
    def default_model(self) -> ChatDeepSeek | ChatGroq:
        """
        Returns whichever model the active MODEL_PROFILE points to. Existing
        code (main_agent.py, checkpointed_agent.py) that just does
        `settings.default_model` keeps working unchanged.
        """
        if self.model_profile == "cheap":
            return self.get_cheap_model()
        return self.get_primary_model()


settings = Settings()
