import asyncio
from decimal import Decimal

import pytest

from support.db.session import SessionFactory, unit_of_work
from support.domain.enums import RefundStatus, TicketCategory, TicketPriority, TicketStatus
from support.domain.errors import Conflict, NotFound, PolicyViolation
from support.domain.policies import RefundPolicy, ReturnPolicy
from support.services import audit
from support.services.billing import BillingService
from support.services.orders import OrderService
from support.services.tickets import TicketService

pytestmark = pytest.mark.integration
ACTOR = "agent:test"


async def test_small_refund_is_auto_approved_and_audited(
    sessions: SessionFactory, refund_policy: RefundPolicy
) -> None:
    async with unit_of_work(sessions) as s:
        r = await BillingService(s, refund_policy).request_refund(
            customer_id="C001", invoice_id="inv-2002", reason="duplicate", amount=None, actor=ACTOR
        )
    assert r.auto_approved and r.refund.status == RefundStatus.APPROVED and r.ticket is None
    assert r.refund.amount == Decimal("29.00")
    async with unit_of_work(sessions) as s:
        entries = await audit.list_entries(s, customer_id="C001")
    assert [e.action for e in entries] == ["refund.requested"]


async def test_large_refund_creates_ticket_and_human_can_approve(
    sessions: SessionFactory, refund_policy: RefundPolicy
) -> None:
    async with unit_of_work(sessions) as s:
        r = await BillingService(s, refund_policy).request_refund(
            customer_id="C003", invoice_id="INV-2005", reason="unused seats", amount=None, actor=ACTOR
        )
    assert r.refund.status == RefundStatus.PENDING_APPROVAL
    assert r.ticket is not None and r.ticket.priority == TicketPriority.HIGH

    async with unit_of_work(sessions) as s:
        decided = await BillingService(s, refund_policy).decide(
            r.refund.id, approve=True, note="ok", actor="user:agent@nimbus.example"
        )
    assert decided.status == RefundStatus.APPROVED
    async with unit_of_work(sessions) as s:
        (ticket,) = await TicketService(s).list(customer_id="C003")
        assert ticket.status == TicketStatus.RESOLVED
        with pytest.raises(Conflict):
            await BillingService(s, refund_policy).decide(r.refund.id, approve=False, note=None, actor="x")


async def test_cannot_touch_another_customers_invoice_or_order(
    sessions: SessionFactory, refund_policy: RefundPolicy, return_policy: ReturnPolicy
) -> None:
    async with unit_of_work(sessions) as s:
        with pytest.raises(NotFound):
            await BillingService(s, refund_policy).request_refund(
                customer_id="C001", invoice_id="INV-2005", reason="x", amount=None, actor=ACTOR
            )
        with pytest.raises(NotFound):
            await OrderService(s, return_policy).get_order("C001", "ORD-1005")


async def test_concurrent_refunds_on_same_invoice_only_one_wins(
    sessions: SessionFactory, refund_policy: RefundPolicy
) -> None:
    async def attempt() -> str:
        try:
            async with unit_of_work(sessions) as s:
                await BillingService(s, refund_policy).request_refund(
                    customer_id="C001", invoice_id="INV-2001", reason="race", amount=None, actor=ACTOR
                )
            return "ok"
        except PolicyViolation:
            return "rejected"

    results = sorted(await asyncio.gather(attempt(), attempt(), attempt()))
    assert results == ["ok", "rejected", "rejected"]


async def test_return_outside_window_rejected(sessions: SessionFactory, return_policy: ReturnPolicy) -> None:
    async with unit_of_work(sessions) as s:
        with pytest.raises(PolicyViolation, match="return window"):
            await OrderService(s, return_policy).start_return(
                customer_id="C002", order_id="ORD-1004", reason="broken", actor=ACTOR
            )
        ret = await OrderService(s, return_policy).start_return(
            customer_id="C001", order_id="ORD-1001", reason="keys stick", actor=ACTOR
        )
    assert ret.status == "label_sent"


async def test_ticket_creation_is_idempotent_per_conversation(sessions: SessionFactory) -> None:
    import uuid

    conv = uuid.uuid4()
    async with unit_of_work(sessions) as s:
        t1, created1 = await TicketService(s).create(
            customer_id="C001",
            category=TicketCategory.TECHNICAL,
            priority=TicketPriority.NORMAL,
            summary="crash",
            actor=ACTOR,
            conversation_id=conv,
        )
        t2, created2 = await TicketService(s).create(
            customer_id="C001",
            category=TicketCategory.TECHNICAL,
            priority=TicketPriority.NORMAL,
            summary="crash again",
            actor=ACTOR,
            conversation_id=conv,
        )
    assert created1 and not created2 and t1.id == t2.id
