"""A scripted chat model for offline tests: no API key, deterministic output."""
from __future__ import annotations

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda


class ScriptedChatModel(BaseChatModel):
    """Returns queued AIMessages in order. `bind_tools` is a no-op."""
    responses: list[Any] = []
    calls: list[list] = []

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.calls.append(messages)
        if not self.responses:
            raise AssertionError("ScriptedChatModel ran out of responses")
        msg = self.responses.pop(0)
        if isinstance(msg, str):
            msg = AIMessage(msg)
        return ChatResult(generations=[ChatGeneration(message=msg)])

    def bind_tools(self, tools, **kwargs):
        return self

    def with_structured_output(self, schema, **kwargs):
        def run(_messages):
            if not self.responses:
                raise AssertionError("ScriptedChatModel ran out of route decisions")
            return schema(**self.responses.pop(0))
        return RunnableLambda(run)


def call(name: str, args: dict, idx: int = 0) -> AIMessage:
    """Build an AIMessage that requests one tool call."""
    return AIMessage("", tool_calls=[{"name": name, "args": args, "id": f"call_{name}_{idx}"}])
