from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import StreamingResponse

from support.api.chat import ChatEvent, ChatRunner
from support.api.deps import ContainerDep, CustomerDep, PrincipalDep, SessionDep, rate_limited
from support.api.schemas import MessageIn, TranscriptMessage, TurnResult
from support.db.session import unit_of_work
from support.domain.errors import DomainError
from support.domain.schemas import AccountOverview, ConversationOut
from support.services.customers import ConversationService, CustomerService

router = APIRouter(tags=["conversations"])


def runner(request: Request) -> ChatRunner:
    return request.app.state.chat_runner


@router.get("/me/account", response_model=AccountOverview)
async def my_account(p: CustomerDep, session: SessionDep, c: ContainerDep) -> AccountOverview:
    assert p.customer_id
    return await CustomerService(session).overview(p.customer_id, c.refund_policy, c.return_policy)


@router.post("/conversations", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def create_conversation(p: CustomerDep, session: SessionDep) -> ConversationOut:
    assert p.customer_id
    return await ConversationService(session).create(p.customer_id)


@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(p: CustomerDep, session: SessionDep) -> list[ConversationOut]:
    assert p.customer_id
    return await ConversationService(session).list(p.customer_id)


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: uuid.UUID, p: CustomerDep, c: ContainerDep, chat: ChatRunner = Depends(runner)
) -> None:
    """Delete one of the customer's conversations and its message history (409 while replying)."""
    assert p.customer_id
    customer_id = p.customer_id

    async def remove_metadata() -> None:
        async with unit_of_work(c.sessions) as session:
            await ConversationService(session).delete(conversation_id, customer_id=customer_id)

    await chat.delete(conversation_id, remove_metadata)


@router.get("/conversations/{conversation_id}/messages", response_model=list[TranscriptMessage])
async def get_messages(
    conversation_id: uuid.UUID, p: PrincipalDep, session: SessionDep, chat: ChatRunner = Depends(runner)
) -> list[TranscriptMessage]:
    """Customers can read their own conversations; staff can read any."""
    await ConversationService(session).get(conversation_id, customer_id=None if p.is_agent else p.customer_id)
    return await chat.transcript(conversation_id)


def _sse(seq: int, event: ChatEvent) -> str:
    return f"id: {seq}\nevent: {event.type}\ndata: {json.dumps(event.data, default=str)}\n\n"


@router.post(
    "/conversations/{conversation_id}/messages",
    dependencies=[Depends(rate_limited)],
    response_model=None,
    responses={200: {"model": TurnResult, "content": {"text/event-stream": {}}}},
)
async def post_message(
    conversation_id: uuid.UUID,
    body: MessageIn,
    request: Request,
    p: CustomerDep,
    c: ContainerDep,
    chat: ChatRunner = Depends(runner),
) -> StreamingResponse | TurnResult:
    """Send a customer message.

    `Accept: text/event-stream` streams `token`, `trace`, `message`, `error` and `done` events.
    Otherwise the response is a single JSON `TurnResult` once the turn completes.
    """
    assert p.customer_id
    # Short explicit transaction: a request-scoped session would stay open for the whole stream.
    async with unit_of_work(c.sessions) as session:
        await ConversationService(session).get(conversation_id, customer_id=p.customer_id)
    events = chat.start_turn(conversation_id, p.customer_id, body.content)  # 409 raised here, pre-stream

    if "text/event-stream" in request.headers.get("accept", ""):

        async def stream() -> AsyncIterator[str]:
            seq = 0
            async for ev in events:
                seq += 1
                yield _sse(seq, ev)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    trace, final, error = [], None, None
    async for ev in events:
        if ev.type == "trace":
            trace.append(ev.data)
        elif ev.type == "message":
            final = ev.data
        elif ev.type == "error":
            error = ev.data["message"]
    if final is None:
        raise _TurnFailed(error or "The turn did not produce a reply.")
    return TurnResult(
        message=TranscriptMessage(**final["message"]), active_agent=final["active_agent"], events=trace
    )


class _TurnFailed(DomainError):
    code = "turn_failed"
    http_status = 502
