"""SQLAlchemy 2.0 ORM models.

Money is NUMERIC(10,2) / Decimal end to end. Status columns are VARCHAR + CHECK
constraints generated from the domain enums (no native PG enums, which are painful
to migrate). Knowledge-base chunks carry both a pgvector embedding (semantic search)
and a generated tsvector (keyword search) for hybrid retrieval.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Computed,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from support.domain.enums import (
    InvoiceStatus,
    OrderStatus,
    RefundStatus,
    ReturnStatus,
    Role,
    TicketCategory,
    TicketPriority,
    TicketStatus,
)

EMBEDDING_DIM = 1536  # text-embedding-3-small; changing it requires a migration


def _enum(e: type[StrEnum], name: str) -> Enum:
    return Enum(
        e,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda x: [m.value for m in x],
        validate_strings=True,
    )


Money = Numeric(10, 2)
JsonB = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Customer(TimestampMixin, Base):
    __tablename__ = "customers"
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(320), unique=True)
    plan: Mapped[str] = mapped_column(String(32))
    member_since: Mapped[date] = mapped_column(Date)


class User(TimestampMixin, Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[Role] = mapped_column(_enum(Role, "role"))
    display_name: Mapped[str] = mapped_column(String(200))
    customer_id: Mapped[str | None] = mapped_column(ForeignKey("customers.id"), nullable=True)


class Order(TimestampMixin, Base):
    __tablename__ = "orders"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    status: Mapped[OrderStatus] = mapped_column(_enum(OrderStatus, "order_status"))
    total: Mapped[Decimal] = mapped_column(Money)
    items: Mapped[list[str]] = mapped_column(JsonB)
    placed_at: Mapped[date] = mapped_column(Date)
    carrier: Mapped[str | None] = mapped_column(String(32))
    tracking_number: Mapped[str | None] = mapped_column(String(64))
    eta: Mapped[date | None] = mapped_column(Date)
    delivered_at: Mapped[date | None] = mapped_column(Date)
    returns: Mapped[list[Return]] = relationship(back_populates="order", lazy="selectin")


class Invoice(TimestampMixin, Base):
    __tablename__ = "invoices"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Money)
    status: Mapped[InvoiceStatus] = mapped_column(_enum(InvoiceStatus, "invoice_status"))
    description: Mapped[str] = mapped_column(String(300))
    issued_at: Mapped[date] = mapped_column(Date)
    refunds: Mapped[list[Refund]] = relationship(back_populates="invoice", lazy="selectin")


class Refund(TimestampMixin, Base):
    __tablename__ = "refunds"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    invoice_id: Mapped[str] = mapped_column(ForeignKey("invoices.id"), index=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Money)
    reason: Mapped[str] = mapped_column(String(500))
    status: Mapped[RefundStatus] = mapped_column(_enum(RefundStatus, "refund_status"), index=True)
    ticket_id: Mapped[str | None] = mapped_column(ForeignKey("tickets.id"))
    decided_by: Mapped[str | None] = mapped_column(String(320))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(String(500))
    invoice: Mapped[Invoice] = relationship(back_populates="refunds")


class Return(TimestampMixin, Base):
    __tablename__ = "returns"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"))
    reason: Mapped[str] = mapped_column(String(500))
    status: Mapped[ReturnStatus] = mapped_column(_enum(ReturnStatus, "return_status"))
    order: Mapped[Order] = relationship(back_populates="returns")


class Ticket(TimestampMixin, Base):
    __tablename__ = "tickets"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    category: Mapped[TicketCategory] = mapped_column(_enum(TicketCategory, "ticket_category"))
    priority: Mapped[TicketPriority] = mapped_column(_enum(TicketPriority, "ticket_priority"))
    status: Mapped[TicketStatus] = mapped_column(_enum(TicketStatus, "ticket_status"), index=True)
    summary: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Conversation(TimestampMixin, Base):
    """Metadata for a chat thread. Message history lives in the LangGraph checkpointer."""

    __tablename__ = "conversations"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="New conversation")
    active_agent: Mapped[str | None] = mapped_column(String(32))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AuditLog(Base):
    """Append-only record of every state-changing action, by humans or agents."""

    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    actor: Mapped[str] = mapped_column(String(320))  # "agent:billing", "user:<email>"
    action: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[str] = mapped_column(String(64))
    customer_id: Mapped[str | None] = mapped_column(String(16), index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JsonB, default=dict)


# ---------------------------------------------------------------- knowledge base
class KbDocument(Base):
    __tablename__ = "kb_documents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True)
    title: Mapped[str] = mapped_column(String(300))
    url: Mapped[str] = mapped_column(String(500))
    category: Mapped[str] = mapped_column(String(64))
    content_hash: Mapped[str] = mapped_column(String(64))
    embedding_model: Mapped[str] = mapped_column(String(100))
    indexed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    chunks: Mapped[list[KbChunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )


class KbChunk(Base):
    __tablename__ = "kb_chunks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("kb_documents.id", ondelete="CASCADE"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    heading: Mapped[str] = mapped_column(String(500))
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))
    tsv: Mapped[Any] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', coalesce(heading, '') || ' ' || content)", persisted=True)
    )
    document: Mapped[KbDocument] = relationship(back_populates="chunks")

    __table_args__ = (
        Index(
            "ix_kb_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_kb_chunks_tsv", "tsv", postgresql_using="gin"),
    )
