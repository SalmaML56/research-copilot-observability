"""
Phase 6, Step 38: the LLM-as-judge model DeepEval scores with.

DeepEval defaults to OpenAI, and there is no OpenAI key in this project, so
the judge is a DeepEvalBaseLLM wrapped around the same LangChain/Groq stack
the agent already uses.

Why openai/gpt-oss-120b on Groq: the agent under test runs on deepseek-chat,
so a DeepSeek judge would be grading its own output. This is not perfectly
neutral either - it shares a family with the gpt-oss-20b open-weight arm of
the Step 42 A/B - so Step 42 has to account for that.

Contract (read from deepeval 4.2.3 source, not assumed): metrics call
`generate_with_schema(prompt, schema=PydanticClass)`, which falls back to
`generate(prompt, schema=...)`. Returning a schema instance is accepted;
returning a JSON string is parsed instead.
"""

import os

# Must be set before deepeval is imported: it ships anonymous telemetry.
os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")

from deepeval.models import DeepEvalBaseLLM  # noqa: E402
from langchain_groq import ChatGroq  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from research_copilot.config.settings import settings  # noqa: E402

DEFAULT_JUDGE_MODEL = "openai/gpt-oss-120b"


class GroqJudge(DeepEvalBaseLLM):
    def __init__(self, model_name: str | None = None):
        self._model_name = model_name or os.getenv("JUDGE_MODEL_NAME", DEFAULT_JUDGE_MODEL)
        if not settings.groq_api_key:
            raise RuntimeError("GroqJudge needs GROQ_API_KEY to be set.")
        super().__init__(self._model_name)

    def load_model(self) -> ChatGroq:
        # temperature=0: a judge should be as repeatable as the API allows.
        return ChatGroq(
            model=self._model_name,
            api_key=settings.groq_api_key,
            temperature=0,
            max_tokens=settings.max_tokens,
            timeout=90,
            max_retries=2,
        )

    def _runnable(self, schema: type[BaseModel] | None):
        # method="json_schema", not the default "function_calling": with
        # tool-calling, gpt-oss-120b answered in prose and Groq rejected the
        # call ("Tool choice is required, but model did not call a tool").
        if not schema:
            return self.model
        return self.model.with_structured_output(schema, method="json_schema")

    def generate(self, prompt: str, schema: type[BaseModel] | None = None):
        result = self._runnable(schema).invoke(prompt)
        return result if schema else result.content

    async def a_generate(self, prompt: str, schema: type[BaseModel] | None = None):
        result = await self._runnable(schema).ainvoke(prompt)
        return result if schema else result.content

    def get_model_name(self) -> str:
        return self._model_name
