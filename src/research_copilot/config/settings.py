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
        return ChatDeepSeek(model=self.primary_model_name, api_key=self.deepseek_api_key, max_tokens=self.max_tokens)

    def get_cheap_model(self) -> ChatGroq:
        return ChatGroq(model=self.cheap_model_name, api_key=self.groq_api_key, max_tokens=self.max_tokens)

    @property
    def default_model(self) -> ChatDeepSeek | ChatGroq:
        if self.model_profile == "cheap":
            return self.get_cheap_model()
        return self.get_primary_model()


settings = Settings()
