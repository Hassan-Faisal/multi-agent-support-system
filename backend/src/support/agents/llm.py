from __future__ import annotations

from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from support.settings import Settings


def chat_model_kwargs(model: str, settings: Settings) -> dict[str, Any]:
    """Provider-specific options for one model string, e.g. "openai:gpt-6.1-sol"."""
    kwargs: dict[str, Any] = {"timeout": settings.llm_timeout_s, "max_retries": settings.llm_max_retries}
    if settings.llm_temperature is not None:
        kwargs["temperature"] = settings.llm_temperature
    if model.startswith("openai:") and settings.openai_use_responses_api:
        kwargs["use_responses_api"] = True
    return kwargs


def build_chat_models(settings: Settings) -> tuple[BaseChatModel, BaseChatModel]:
    """(specialist model, triage model). The provider comes from the model string prefix."""

    specialist = init_chat_model(settings.llm_model, **chat_model_kwargs(settings.llm_model, settings))
    # Triage returns a JSON routing decision that's never shown to the customer, so it never
    # needs to stream. Without this, LangGraph's "messages" stream mode would stream it too,
    # adding a fragile partial-JSON parsing path for no benefit.
    triage = init_chat_model(
        settings.triage_model, disable_streaming=True, **chat_model_kwargs(settings.triage_model, settings)
    )
    return specialist, triage
