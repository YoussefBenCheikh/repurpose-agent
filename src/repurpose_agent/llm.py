"""LLM access behind a tiny protocol so nodes stay testable and provider-agnostic."""

import logging
from typing import Protocol, TypeVar

from langchain_anthropic import ChatAnthropic
from langchain_core.exceptions import OutputParserException
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, ValidationError

from repurpose_agent.config import Settings

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class StructuredLLM(Protocol):
    def generate(
        self, schema: type[T], system: str, user: str, config: RunnableConfig | None = None
    ) -> T:
        """`config` is the node's RunnableConfig: pass it on so callbacks (usage
        tracking, LangSmith tracing) see the call as part of the run."""
        ...


class AnthropicLLM:
    """Claude via LangChain, using native structured outputs (`output_config.format`).

    Pydantic validators run after parsing; if they reject the output, the error
    is sent back to the model and it gets another attempt.
    """

    def __init__(self, settings: Settings, max_attempts: int = 3) -> None:
        self.max_attempts = max_attempts
        self.chat = ChatAnthropic(
            model=settings.model,
            effort=settings.effort,
            max_tokens=settings.max_tokens,
            # Server-side fallback: if a safety classifier declines, the API
            # retries on a suitable model instead of returning a refusal.
            betas=["server-side-fallback-2026-07-01"],
            model_kwargs={"extra_body": {"fallbacks": "default"}},
        )

    def generate(
        self, schema: type[T], system: str, user: str, config: RunnableConfig | None = None
    ) -> T:
        structured = self.chat.with_structured_output(schema, method="json_schema")
        messages: list[tuple[str, str]] = [("system", system), ("user", user)]
        last_error: Exception | None = None

        for attempt in range(1, self.max_attempts + 1):
            try:
                call_config: RunnableConfig = {
                    **(config or {}),
                    "run_name": schema.__name__,
                    "metadata": {**(config or {}).get("metadata", {}), "attempt": attempt},
                }
                return structured.invoke(messages, config=call_config)  # type: ignore[return-value]
            except (ValidationError, OutputParserException) as e:
                last_error = e
                log.warning("%s failed validation (attempt %d): %s", schema.__name__, attempt, e)
                messages = [
                    ("system", system),
                    (
                        "user",
                        f"{user}\n\nYour previous answer was rejected by validation:\n{e}\n"
                        "Fix every problem listed and answer again.",
                    ),
                ]
        raise RuntimeError(
            f"{schema.__name__} still invalid after {self.max_attempts} attempts"
        ) from last_error
