from __future__ import annotations

from collections.abc import Callable
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from support.db.models import Order, Return
from support.domain.enums import ReturnStatus
from support.domain.errors import NotFound
from support.domain.policies import ReturnPolicy, check_return_allowed
from support.domain.schemas import OrderOut, ReturnOut, new_id
from support.services import audit


class OrderService:
    def __init__(self, session: AsyncSession, policy: ReturnPolicy, today: Callable[[], date] = date.today):
        self.s, self.policy, self.today = session, policy, today

    async def list_orders(self, customer_id: str) -> list[OrderOut]:
        rows = await self.s.scalars(
            select(Order).where(Order.customer_id == customer_id).order_by(Order.placed_at.desc())
        )
        return [OrderOut.model_validate(o) for o in rows.all()]

    async def _owned(self, customer_id: str, order_id: str, *, lock: bool = False) -> Order:
        q = select(Order).where(Order.id == order_id.upper(), Order.customer_id == customer_id)
        order = await self.s.scalar(q.with_for_update() if lock else q)
        if order is None:
            raise NotFound(f"Order {order_id} was not found on this account.")
        return order

    async def get_order(self, customer_id: str, order_id: str) -> OrderOut:
        return OrderOut.model_validate(await self._owned(customer_id, order_id))

    async def start_return(self, *, customer_id: str, order_id: str, reason: str, actor: str) -> ReturnOut:
        order = await self._owned(customer_id, order_id, lock=True)
        check_return_allowed(order_status=order.status, delivered_at=order.delivered_at,
                             has_existing_return=bool(order.returns), today=self.today(), policy=self.policy)
        ret = Return(id=new_id("RT"), order_id=order.id, customer_id=customer_id, reason=reason[:500],
                     status=ReturnStatus.LABEL_SENT)
        self.s.add(ret)
        await self.s.flush()
        await self.s.refresh(ret)
        await audit.record(self.s, actor=actor, action="return.started", entity_type="return",
                           entity_id=ret.id, customer_id=customer_id, data={"order_id": order.id})
        return ReturnOut.model_validate(ret)
