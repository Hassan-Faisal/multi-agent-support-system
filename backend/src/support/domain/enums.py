from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    CUSTOMER = "customer"
    AGENT = "agent"  # human support staff


class OrderStatus(StrEnum):
    PROCESSING = "processing"
    IN_TRANSIT = "in_transit"
    DELAYED = "delayed"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class InvoiceStatus(StrEnum):
    PAID = "paid"
    OVERDUE = "overdue"
    VOID = "void"


class RefundStatus(StrEnum):
    APPROVED = "approved"
    PENDING_APPROVAL = "pending_approval"
    REJECTED = "rejected"


class ReturnStatus(StrEnum):
    LABEL_SENT = "label_sent"
    RECEIVED = "received"
    REFUNDED = "refunded"


class TicketStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"


class TicketPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class TicketCategory(StrEnum):
    BILLING = "billing"
    TECHNICAL = "technical"
    ORDERS = "orders"
    ACCOUNT = "account"
    OTHER = "other"


class AgentName(StrEnum):
    BILLING = "billing"
    TECHNICAL = "technical"
    ORDERS = "orders"
    ESCALATION = "escalation"
