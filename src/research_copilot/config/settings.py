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

load_dotenv()


class Settings:
    environment: str = os.getenv("ENVIRONMENT", "dev")
    deepseek_api_key: str | None = os.getenv("DEEPSEEK_API_KEY")

    # deepseek-chat = DeepSeek-V3, supports tool calling (needed for our
    # web_search / write_file / read_file tools).
    # deepseek-reasoner = R1, does NOT support tool calling — do not use
    # it for this project's agents.
    default_model_name: str = os.getenv("DEFAULT_MODEL_NAME", "deepseek-chat")
    max_tokens: int = int(os.getenv("MAX_TOKENS", "4096"))

    def validate(self) -> None:
        """
        Fail loudly and early if a required secret is missing, instead of
        letting the agent fail deep inside a LangGraph call with a confusing
        stack trace.
        """
        if not self.deepseek_api_key:
            raise RuntimeError(
                "DEEPSEEK_API_KEY is not set. Add it to .env before "
                "running any agent code."
            )

    @property
    def default_model(self) -> ChatDeepSeek:
        return ChatDeepSeek(
            model=self.default_model_name,
            api_key=self.deepseek_api_key,
            max_tokens=self.max_tokens,
        )


settings = Settings()
