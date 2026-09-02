"""
Central place to read configuration/environment variables from.

Why this file exists: every other module should import settings from HERE,
never call os.environ directly. That way, if we later need to validate a
value, rename an env var, or add a default, we change it in one place instead
of hunting through the whole codebase.
"""

import os
from dotenv import load_dotenv
from langchain_groq import ChatGroq

load_dotenv()


class Settings:
    environment: str = os.getenv("ENVIRONMENT", "dev")
    groq_api_key: str | None = os.getenv("GROQ_API_KEY")
    default_model_name: str = os.getenv("DEFAULT_MODEL_NAME", "openai/gpt-oss-120b")
    max_tokens: int = int(os.getenv("MAX_TOKENS", "4096"))

    def validate(self) -> None:
        if not self.groq_api_key:
            raise RuntimeError(
                "GROQ_API_KEY is not set. Copy .env.example to .env "
                "and fill in your key before running any agent code."
            )

    @property
    def default_model(self) -> ChatGroq:
        return ChatGroq(
            model=self.default_model_name,
            api_key=self.groq_api_key,
            max_tokens=self.max_tokens,
        )


settings = Settings()
