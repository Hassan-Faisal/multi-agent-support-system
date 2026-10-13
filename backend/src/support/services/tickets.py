from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from support.db.models import Ticket
from support.domain.enums import TicketCategory, TicketPriority, TicketStatus
from support.domain.errors import NotFound
from support.domain.schemas import TicketOut, new_id
from support.services import audit


class TicketService:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def create(
        self,
        *,
        customer_id: str,
        category: TicketCategory,
        priority: TicketPriority,
        summary: str,
        actor: str,
        conversation_id: uuid.UUID | None = None,
    ) -> tuple[TicketOut, bool]:
        """Create a ticket, or return the open one already filed for this conversation
        and category (agents retry; customers repeat themselves). Returns (ticket, created)."""
        if conversation_id is not None:
            existing = await self.s.scalar(
                select(Ticket).where(
                    Ticket.conversation_id == conversation_id,
                    Ticket.category == category,
                    Ticket.status != TicketStatus.RESOLVED,
                )
            )
            if existing:
                return TicketOut.model_validate(existing), False

        t = Ticket(id=new_id("TKT"), customer_id=customer_id, conversation_id=conversation_id,
                   category=category, priority=priority, status=TicketStatus.OPEN, summary=summary.strip())
        self.s.add(t)
        await self.s.flush()
        await self.s.refresh(t)
        await audit.record(self.s, actor=actor, action="ticket.created", entity_type="ticket", entity_id=t.id,
                           customer_id=customer_id,
                           data={"category": category.value, "priority": priority.value})
        return TicketOut.model_validate(t), True

    async def list(self, *, status: TicketStatus | None = None, customer_id: str | None = None) -> list[TicketOut]:
        q = select(Ticket).order_by(Ticket.created_at.desc())
        if status:
            q = q.where(Ticket.status == status)
        if customer_id:
            q = q.where(Ticket.customer_id == customer_id)
        return [TicketOut.model_validate(t) for t in (await self.s.scalars(q)).all()]

    async def set_status(self, ticket_id: str, status: TicketStatus, *, actor: str) -> TicketOut:
        t = await self.s.get(Ticket, ticket_id, with_for_update=True)
        if t is None:
            raise NotFound(f"Ticket {ticket_id} not found.")
        previous = t.status
        t.status = status
        await self.s.flush()
        await self.s.refresh(t)
        await audit.record(self.s, actor=actor, action="ticket.status_changed", entity_type="ticket",
                           entity_id=t.id, customer_id=t.customer_id,
                           data={"from": previous.value, "to": status.value})
        return TicketOut.model_validate(t)
