from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from support.db.models import AuditLog
from support.domain.schemas import AuditOut


async def record(
    session: AsyncSession,
    *,
    actor: str,
    action: str,
    entity_type: str,
    entity_id: str,
    customer_id: str | None,
    data: dict[str, Any] | None = None,
) -> None:
    """Append an audit entry inside the caller's transaction, so it commits atomically
    with the change it describes."""
    session.add(AuditLog(actor=actor, action=action, entity_type=entity_type, entity_id=entity_id,
                         customer_id=customer_id, data=data or {}))


async def list_entries(session: AsyncSession, *, limit: int = 100, customer_id: str | None = None) -> list[AuditOut]:
    q = select(AuditLog).order_by(AuditLog.at.desc(), AuditLog.id.desc()).limit(limit)
    if customer_id:
        q = q.where(AuditLog.customer_id == customer_id)
    return [AuditOut.model_validate(r) for r in (await session.scalars(q)).all()]
