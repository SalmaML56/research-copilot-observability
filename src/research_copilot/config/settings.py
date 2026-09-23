"""
Central place to read configuration/environment variables from.
"""

import os
from dotenv import load_dotenv
from langchain_deepseek import ChatDeepSeek
from langchain_groq import ChatGroq

load_dotenv()

VALID_MODEL_PROFILES = ("primary", "cheap")


class Settings:
    environment: str = os.getenv("ENVIRONMENT", "dev")
    deepseek_api_key: str | None = os.getenv("DEEPSEEK_API_KEY")
    primary_model_name: str = os.getenv("DEFAULT_MODEL_NAME", "deepseek-chat")
    max_tokens: int = int(os.getenv("MAX_TOKENS", "4096"))
    groq_api_key: str | None = os.getenv("GROQ_API_KEY")
    cheap_model_name: str = os.getenv("CHEAP_MODEL_NAME", "openai/gpt-oss-20b")
    model_profile: str = os.getenv("MODEL_PROFILE", "primary")
    prompt_version: str = os.getenv("PROMPT_VERSION", "v1")
    # Phase 7, step 46: agent checkpoints (dedicated checkpoint-postgres).
    # Lives here, not in checkpointed_agent.py, because metrics_setup.py
    # needs it too and checkpointed_agent.py already imports metrics_setup.
    checkpoint_db_uri: str = os.getenv(
        "CHECKPOINT_DB_URI", "postgresql://checkpoints:checkpoints@localhost:5433/checkpoints"
    )

    def validate(self) -> None:
        if self.model_profile not in VALID_MODEL_PROFILES:
            raise RuntimeError(
                f"MODEL_PROFILE={self.model_profile!r} is not valid. "
                f"Must be one of {VALID_MODEL_PROFILES}."
            )
        if self.model_profile == "primary" and not self.deepseek_api_key:
            raise RuntimeError("MODEL_PROFILE is 'primary' but DEEPSEEK_API_KEY is not set.")
        if self.model_profile == "cheap" and not self.groq_api_key:
            raise RuntimeError("MODEL_PROFILE is 'cheap' but GROQ_API_KEY is not set.")

    def get_primary_model(self) -> ChatDeepSeek:
        # Step 18 fix: without a timeout, a slow/stalled LLM API response
        # hangs the request forever (confirmed via py-spy: threads stuck in
        # ssl.recv() with no timeout set, blocking the whole agent run).
        return ChatDeepSeek(
            model=self.primary_model_name,
            api_key=self.deepseek_api_key,
            max_tokens=self.max_tokens,
            timeout=90,
            max_retries=2,
        )

    def get_cheap_model(self) -> ChatGroq:
        # Step 18 fix: same reasoning as get_primary_model() above.
        return ChatGroq(
            model=self.cheap_model_name,
            api_key=self.groq_api_key,
            max_tokens=self.max_tokens,
            timeout=90,
            max_retries=2,
        )

    @property
    def default_model(self) -> ChatDeepSeek | ChatGroq:
        if self.model_profile == "cheap":
            return self.get_cheap_model()
        return self.get_primary_model()


settings = Settings()
