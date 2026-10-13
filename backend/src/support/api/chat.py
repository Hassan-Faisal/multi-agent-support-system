"""Runs one customer turn through the graph and turns it into a stream of events.

Design notes:
- The graph runs in its own task that feeds a queue. If the browser disconnects
  mid-stream, the turn still completes and is checkpointed, so the reply is there
  when the customer comes back, instead of leaving a half-finished turn.
- One turn per conversation at a time (409 otherwise): concurrent turns on one
  thread would interleave checkpoint writes.
- Event types: token, trace, message, error, done. The final `message` is
  authoritative; tokens are a progressive preview.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any, cast

import structlog
from langchain_core.messages import AIMessage, AIMessageChunk, AnyMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver

from support.agents.graph import text_of
from support.agents.state import AGENTS
from support.api.container import Container
from support.api.schemas import Source, TranscriptMessage
from support.db.session import unit_of_work
from support.domain.errors import Conflict
from support.observability.logs import get_logger
from support.observability.metrics import TURN_LATENCY, TURNS
from support.services.customers import ConversationService

log = get_logger(__name__)
_DONE = object()


@dataclass(frozen=True)
class ChatEvent:
    type: str
    data: dict[str, Any]


def run_config(conversation_id: uuid.UUID, customer_id: str) -> RunnableConfig:
    return {
        "configurable": {
            "thread_id": str(conversation_id),
            "conversation_id": str(conversation_id),
            "customer_id": customer_id,
        },
        "metadata": {"customer_id": customer_id},
        "run_name": "support_turn",
    }


def to_transcript(m: AnyMessage) -> TranscriptMessage | None:
    """Customer-visible messages only: no tool calls, tool results or empty turns."""
    if isinstance(m, HumanMessage):
        return TranscriptMessage(id=m.id, role="customer", content=text_of(m))
    if isinstance(m, AIMessage) and not m.tool_calls and text_of(m).strip():
        sources = [Source(**s) for s in m.response_metadata.get("sources", [])]
        return TranscriptMessage(id=m.id, role="assistant", agent=m.name, content=text_of(m), sources=sources)
    return None


class ChatRunner:
    def __init__(self, container: Container) -> None:
        self.c = container
        self._busy: set[uuid.UUID] = set()
        self._tasks: set[asyncio.Task[None]] = set()

    async def transcript(self, conversation_id: uuid.UUID) -> list[TranscriptMessage]:
        snap = await self.c.graph.aget_state({"configurable": {"thread_id": str(conversation_id)}})
        msgs = (snap.values or {}).get("messages", [])
        return [t for m in msgs if (t := to_transcript(m))]

    async def delete(
        self, conversation_id: uuid.UUID, remove_metadata: Callable[[], Awaitable[None]]
    ) -> None:
        """Delete a conversation's metadata, then its message history in the checkpointer.
        Refused while a reply is being written, and the conversation is held busy meanwhile
        so a new turn can't start halfway through."""
        if conversation_id in self._busy:
            raise Conflict("Wait for the current reply to finish before deleting this conversation.")
        self._busy.add(conversation_id)
        try:
            await remove_metadata()
            checkpointer = self.c.graph.checkpointer
            if isinstance(checkpointer, BaseCheckpointSaver):
                await checkpointer.adelete_thread(str(conversation_id))
        finally:
            self._busy.discard(conversation_id)

    def start_turn(self, conversation_id: uuid.UUID, customer_id: str, text: str) -> AsyncIterator[ChatEvent]:
        """Start the turn now (raising Conflict before any response is sent if one is
        already running) and return an iterator over its events."""
        if conversation_id in self._busy:
            raise Conflict("A reply is still being written for this conversation.")
        self._busy.add(conversation_id)
        queue: asyncio.Queue[Any] = asyncio.Queue()
        task = asyncio.create_task(self._run(conversation_id, customer_id, text, queue))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

        async def events() -> AsyncIterator[ChatEvent]:
            while (item := await queue.get()) is not _DONE:
                yield item

        return events()

    async def _run(
        self, conversation_id: uuid.UUID, customer_id: str, text: str, queue: asyncio.Queue[Any]
    ) -> None:
        structlog.contextvars.bind_contextvars(conversation_id=str(conversation_id))
        config = run_config(conversation_id, customer_id)
        started, outcome = time.perf_counter(), "ok"
        try:
            async with asyncio.timeout(self.c.settings.turn_timeout_s):
                async for part in self.c.graph.astream(
                    {"messages": [HumanMessage(text, id=str(uuid.uuid4()))]},
                    config,
                    stream_mode=["messages", "custom"],
                ):
                    # with a list of modes, each part is a (mode, payload) tuple
                    mode, chunk = cast(tuple[str, Any], part)
                    if mode == "custom" and "trace" in chunk:
                        queue.put_nowait(ChatEvent("trace", chunk["trace"]))
                    elif mode == "messages":
                        msg, meta = chunk
                        node = meta.get("langgraph_node")
                        if isinstance(msg, AIMessageChunk) and node in AGENTS and (delta := text_of(msg)):
                            queue.put_nowait(ChatEvent("token", {"agent": node, "text": delta}))

            snap = await self.c.graph.aget_state(config)
            state = snap.values
            final = next((t for m in reversed(state["messages"]) if (t := to_transcript(m))), None)
            if final is None or final.role != "assistant":
                raise RuntimeError("turn finished without an assistant reply")
            async with unit_of_work(self.c.sessions) as s:
                await ConversationService(s).touch(
                    conversation_id, active_agent=state.get("active_agent"), first_message=text
                )
            queue.put_nowait(
                ChatEvent(
                    "message",
                    {"message": final.model_dump(mode="json"), "active_agent": state.get("active_agent")},
                )
            )
            log.info(
                "turn.completed",
                agent=final.agent,
                events=len(state.get("events", [])),
                ms=round((time.perf_counter() - started) * 1000),
            )
        except TimeoutError:
            outcome = "timeout"
            log.error("turn.timeout")
            queue.put_nowait(ChatEvent("error", {"message": "That took too long. Please try again."}))
        except Exception:
            outcome = "error"
            log.exception("turn.failed")
            queue.put_nowait(
                ChatEvent("error", {"message": "Something went wrong on our side. Please try again."})
            )
        finally:
            TURNS.labels(outcome).inc()
            TURN_LATENCY.observe(time.perf_counter() - started)
            queue.put_nowait(ChatEvent("done", {}))
            queue.put_nowait(_DONE)
            self._busy.discard(conversation_id)

    async def drain(self) -> None:
        """Let in-flight turns finish on shutdown."""
        if self._tasks:
            await asyncio.wait(self._tasks, timeout=self.c.settings.turn_timeout_s)
