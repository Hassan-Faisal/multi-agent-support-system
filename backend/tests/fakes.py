"""Deterministic stand-ins for LLMs, so graph behaviour is testable without API keys."""
from __future__ import annotations

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable, RunnableLambda


class ScriptedChatModel(BaseChatModel):
    """Replays queued responses in order and records every prompt it was sent.

    Queue AIMessages / strings for agents, and dicts for structured-output (triage) calls.
    """

    responses: list[Any] = []
    calls: list[list[BaseMessage]] = []

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None,
                  **kwargs: Any) -> ChatResult:
        self.calls.append(messages)
        if not self.responses:
            raise AssertionError("ScriptedChatModel ran out of responses")
        msg = self.responses.pop(0)
        if isinstance(msg, str):
            msg = AIMessage(msg)
        return ChatResult(generations=[ChatGeneration(message=msg)])

    def bind_tools(self, tools: Any, **kwargs: Any) -> Runnable[Any, Any]:  # type: ignore[override]
        return self

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Runnable[Any, Any]:  # type: ignore[override]
        def run(messages: list[BaseMessage]) -> Any:
            self.calls.append(messages)
            if not self.responses:
                raise AssertionError("ScriptedChatModel ran out of route decisions")
            return schema(**self.responses.pop(0))

        return RunnableLambda(run)


def scripted(*responses: Any) -> ScriptedChatModel:
    return ScriptedChatModel(responses=list(responses), calls=[])


def tool_call(name: str, args: dict[str, Any] | None = None, idx: int = 0) -> AIMessage:
    return AIMessage("", tool_calls=[{"name": name, "args": args or {}, "id": f"call_{name}_{idx}",
                                      "type": "tool_call"}])
