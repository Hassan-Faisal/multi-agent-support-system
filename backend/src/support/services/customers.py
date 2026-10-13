from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from support.db.models import Conversation, Customer, Refund, Ticket
from support.domain.enums import RefundStatus, TicketStatus
from support.domain.errors import NotFound
from support.domain.policies import RefundPolicy, ReturnPolicy
from support.domain.schemas import AccountOverview, ConversationOut, CustomerOut
from support.services.billing import BillingService
from support.services.orders import OrderService
from support.services.tickets import TicketService


class CustomerService:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def get(self, customer_id: str) -> CustomerOut:
        c = await self.s.get(Customer, customer_id)
        if c is None:
            raise NotFound(f"Customer {customer_id} not found.")
        return CustomerOut.model_validate(c)

    async def overview(self, customer_id: str, refund: RefundPolicy, ret: ReturnPolicy) -> AccountOverview:
        return AccountOverview(
            customer=await self.get(customer_id),
            orders=await OrderService(self.s, ret).list_orders(customer_id),
            invoices=await BillingService(self.s, refund).list_invoices(customer_id),
            tickets=await TicketService(self.s).list(customer_id=customer_id),
        )


class ConversationService:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def create(self, customer_id: str) -> ConversationOut:
        c = Conversation(customer_id=customer_id)
        self.s.add(c)
        await self.s.flush()
        await self.s.refresh(c)
        return ConversationOut.model_validate(c)

    async def get(self, conversation_id: uuid.UUID, *, customer_id: str | None) -> ConversationOut:
        """`customer_id=None` means a staff caller who may read any conversation."""
        q = select(Conversation).where(Conversation.id == conversation_id)
        if customer_id is not None:
            q = q.where(Conversation.customer_id == customer_id)
        c = await self.s.scalar(q)
        if c is None:
            raise NotFound("Conversation not found.")
        return ConversationOut.model_validate(c)

    async def list(self, customer_id: str, limit: int = 50) -> list[ConversationOut]:
        rows = await self.s.scalars(
            select(Conversation).where(Conversation.customer_id == customer_id)
            .order_by(Conversation.updated_at.desc()).limit(limit)
        )
        return [ConversationOut.model_validate(c) for c in rows.all()]

    async def touch(self, conversation_id: uuid.UUID, *, active_agent: str | None, first_message: str | None) -> None:
        c = await self.s.get(Conversation, conversation_id)
        if c is None:
            return
        c.active_agent = active_agent
        c.updated_at = func.now()
        if first_message and c.title == "New conversation":
            c.title = first_message[:80] + ("…" if len(first_message) > 80 else "")


async def queue_stats(session: AsyncSession) -> dict[str, int]:
    """Counts for the staff dashboard."""
    async def count(q: object) -> int:
        return int(await session.scalar(q) or 0)  # type: ignore[call-overload]

    return {
        "open_tickets": await count(select(func.count()).select_from(Ticket)
                                    .where(Ticket.status != TicketStatus.RESOLVED)),
        "urgent_tickets": await count(select(func.count()).select_from(Ticket)
                                      .where(Ticket.status != TicketStatus.RESOLVED, Ticket.priority == "urgent")),
        "pending_refunds": await count(select(func.count()).select_from(Refund)
                                       .where(Refund.status == RefundStatus.PENDING_APPROVAL)),
        "conversations": await count(select(func.count()).select_from(Conversation)),
    }
