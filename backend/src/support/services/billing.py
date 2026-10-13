from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from support.db.models import Invoice, Refund
from support.domain.enums import RefundStatus, TicketCategory, TicketPriority, TicketStatus
from support.domain.errors import Conflict, NotFound
from support.domain.policies import RefundPolicy, decide_refund
from support.domain.schemas import InvoiceOut, RefundOut, RefundResult, new_id
from support.services import audit
from support.services.tickets import TicketService


class BillingService:
    def __init__(self, session: AsyncSession, policy: RefundPolicy, today: Callable[[], date] = date.today):
        self.s, self.policy, self.today = session, policy, today

    async def list_invoices(self, customer_id: str) -> list[InvoiceOut]:
        rows = await self.s.scalars(
            select(Invoice).where(Invoice.customer_id == customer_id).order_by(Invoice.issued_at.desc())
        )
        return [InvoiceOut.model_validate(r) for r in rows.all()]

    async def request_refund(
        self,
        *,
        customer_id: str,
        invoice_id: str,
        reason: str,
        amount: Decimal | None,
        actor: str,
        conversation_id: uuid.UUID | None = None,
    ) -> RefundResult:
        # Row lock serializes concurrent refund attempts on the same invoice, so the
        # "one refund per invoice" rule can't be raced by double-submits.
        inv = await self.s.scalar(
            select(Invoice)
            .where(Invoice.id == invoice_id.upper(), Invoice.customer_id == customer_id)
            .with_for_update()
        )
        if inv is None:  # same message whether it doesn't exist or belongs to someone else
            raise NotFound(f"Invoice {invoice_id} was not found on this account.")

        decision = decide_refund(
            invoice_amount=inv.amount,
            invoice_status=inv.status,
            issued_at=inv.issued_at,
            has_existing_refund=bool(inv.refunds),
            requested_amount=amount,
            today=self.today(),
            policy=self.policy,
        )

        ticket = None
        if not decision.auto_approve:
            ticket, _ = await TicketService(self.s).create(
                customer_id=customer_id,
                category=TicketCategory.BILLING,
                priority=TicketPriority.HIGH,
                summary=(
                    f"Refund approval needed: {decision.amount} on {inv.id} ({inv.description}). "
                    f"Customer reason: {reason}"
                ),
                actor=actor,
                conversation_id=conversation_id,
            )

        refund = Refund(
            id=new_id("RF"),
            invoice_id=inv.id,
            customer_id=customer_id,
            amount=decision.amount,
            reason=reason[:500],
            status=RefundStatus.APPROVED if decision.auto_approve else RefundStatus.PENDING_APPROVAL,
            ticket_id=ticket.id if ticket else None,
            decided_by="policy:auto" if decision.auto_approve else None,
            decided_at=datetime.now(UTC) if decision.auto_approve else None,
        )
        self.s.add(refund)
        await self.s.flush()
        await self.s.refresh(refund)
        await audit.record(
            self.s,
            actor=actor,
            action="refund.requested",
            entity_type="refund",
            entity_id=refund.id,
            customer_id=customer_id,
            data={"invoice_id": inv.id, "amount": str(decision.amount), "status": refund.status.value},
        )
        return RefundResult(
            refund=RefundOut.model_validate(refund), ticket=ticket, auto_approved=decision.auto_approve
        )

    async def list_refunds(self, status: RefundStatus | None = None) -> list[RefundOut]:
        q = select(Refund).order_by(Refund.created_at.desc())
        if status:
            q = q.where(Refund.status == status)
        return [RefundOut.model_validate(r) for r in (await self.s.scalars(q)).all()]

    async def decide(self, refund_id: str, *, approve: bool, note: str | None, actor: str) -> RefundOut:
        """Human decision on a refund that exceeded the auto-approval limit."""
        refund = await self.s.get(Refund, refund_id, with_for_update=True)
        if refund is None:
            raise NotFound(f"Refund {refund_id} not found.")
        if refund.status != RefundStatus.PENDING_APPROVAL:
            raise Conflict(f"Refund {refund_id} is already {refund.status.value}.")
        refund.status = RefundStatus.APPROVED if approve else RefundStatus.REJECTED
        refund.decided_by, refund.decided_at, refund.decision_note = actor, datetime.now(UTC), note
        if refund.ticket_id:
            await TicketService(self.s).set_status(refund.ticket_id, TicketStatus.RESOLVED, actor=actor)
        await self.s.flush()
        await self.s.refresh(refund)
        await audit.record(
            self.s,
            actor=actor,
            action="refund.approved" if approve else "refund.rejected",
            entity_type="refund",
            entity_id=refund.id,
            customer_id=refund.customer_id,
            data={"amount": str(refund.amount), "note": note},
        )
        return RefundOut.model_validate(refund)
