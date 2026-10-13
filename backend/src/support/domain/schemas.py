"""Read models returned by services. Agents and the API depend on these, never on ORM objects."""

from __future__ import annotations

import secrets
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict

from support.domain.enums import (
    InvoiceStatus,
    OrderStatus,
    RefundStatus,
    ReturnStatus,
    TicketCategory,
    TicketPriority,
    TicketStatus,
)


def new_id(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(3).upper()}"


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CustomerOut(_Out):
    id: str
    name: str
    email: str
    plan: str
    member_since: date


class ReturnOut(_Out):
    id: str
    order_id: str
    reason: str
    status: ReturnStatus
    created_at: datetime


class OrderOut(_Out):
    id: str
    status: OrderStatus
    total: Decimal
    items: list[str]
    placed_at: date
    carrier: str | None
    tracking_number: str | None
    eta: date | None
    delivered_at: date | None
    returns: list[ReturnOut] = []


class RefundOut(_Out):
    id: str
    invoice_id: str
    customer_id: str
    amount: Decimal
    reason: str
    status: RefundStatus
    ticket_id: str | None
    decided_by: str | None
    decided_at: datetime | None
    decision_note: str | None
    created_at: datetime


class InvoiceOut(_Out):
    id: str
    amount: Decimal
    status: InvoiceStatus
    description: str
    issued_at: date
    refunds: list[RefundOut] = []


class TicketOut(_Out):
    id: str
    customer_id: str
    conversation_id: uuid.UUID | None
    category: TicketCategory
    priority: TicketPriority
    status: TicketStatus
    summary: str
    created_at: datetime
    updated_at: datetime


class RefundResult(BaseModel):
    refund: RefundOut
    ticket: TicketOut | None
    auto_approved: bool


class ConversationOut(_Out):
    id: uuid.UUID
    customer_id: str
    title: str
    active_agent: str | None
    created_at: datetime
    updated_at: datetime


class AuditOut(_Out):
    id: int
    at: datetime
    actor: str
    action: str
    entity_type: str
    entity_id: str
    customer_id: str | None
    data: dict[str, Any]


class AccountOverview(BaseModel):
    customer: CustomerOut
    orders: list[OrderOut]
    invoices: list[InvoiceOut]
    tickets: list[TicketOut]
