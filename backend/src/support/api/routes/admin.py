"""Staff console API: queue stats, tickets, refund approvals and the audit log."""

from __future__ import annotations

from fastapi import APIRouter, Query

from support.api.deps import AgentDep, ContainerDep, SessionDep
from support.api.schemas import RefundDecisionIn, TicketUpdateIn
from support.domain.enums import RefundStatus, TicketStatus
from support.domain.schemas import AuditOut, RefundOut, TicketOut
from support.services import audit
from support.services.billing import BillingService
from support.services.customers import queue_stats
from support.services.tickets import TicketService

router = APIRouter(prefix="/admin", tags=["admin"])


def _actor(p: AgentDep) -> str:
    return f"user:{p.display_name}<{p.user_id}>"


@router.get("/stats")
async def stats(_: AgentDep, session: SessionDep) -> dict[str, int]:
    return await queue_stats(session)


@router.get("/tickets", response_model=list[TicketOut])
async def tickets(_: AgentDep, session: SessionDep, status: TicketStatus | None = None) -> list[TicketOut]:
    return await TicketService(session).list(status=status)


@router.patch("/tickets/{ticket_id}", response_model=TicketOut)
async def update_ticket(ticket_id: str, body: TicketUpdateIn, p: AgentDep, session: SessionDep) -> TicketOut:
    return await TicketService(session).set_status(ticket_id, body.status, actor=_actor(p))


@router.get("/refunds", response_model=list[RefundOut])
async def refunds(
    _: AgentDep, session: SessionDep, c: ContainerDep, status: RefundStatus | None = None
) -> list[RefundOut]:
    return await BillingService(session, c.refund_policy).list_refunds(status)


@router.post("/refunds/{refund_id}/decision", response_model=RefundOut)
async def decide_refund(
    refund_id: str, body: RefundDecisionIn, p: AgentDep, session: SessionDep, c: ContainerDep
) -> RefundOut:
    return await BillingService(session, c.refund_policy).decide(
        refund_id, approve=body.approve, note=body.note, actor=_actor(p)
    )


@router.get("/audit", response_model=list[AuditOut])
async def audit_log(
    _: AgentDep, session: SessionDep, limit: int = Query(100, le=500), customer_id: str | None = None
) -> list[AuditOut]:
    return await audit.list_entries(session, limit=limit, customer_id=customer_id)
