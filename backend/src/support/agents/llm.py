from __future__ import annotations

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from support.settings import Settings


def build_chat_models(settings: Settings) -> tuple[BaseChatModel, BaseChatModel]:
    """(specialist model, triage model). Provider is chosen by the model string prefix,
    e.g. "anthropic:claude-sonnet-5-5" or "openai:gpt-4.1"."""

    def make(model: str) -> BaseChatModel:
        return init_chat_model(
            model,
            temperature=settings.llm_temperature,
            timeout=settings.llm_timeout_s,
            max_retries=settings.llm_max_retries,
        )

    return make(settings.llm_model), make(settings.triage_model)
