"""Seed demo data. Dates are relative to today so policy windows behave the same any day.

python -m support.db.seed            # seed if empty
python -m support.db.seed --reset    # wipe business data and reseed
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from support.db.models import Customer, Invoice, Order, User
from support.db.session import create_engine, create_session_factory, unit_of_work
from support.domain.enums import InvoiceStatus, OrderStatus, Role
from support.security.auth import hash_password
from support.settings import get_settings

DEMO_PASSWORD = "demo1234"
BUSINESS_TABLES = (
    "audit_log",
    "refunds",
    "returns",
    "tickets",
    "conversations",
    "users",
    "invoices",
    "orders",
    "customers",
)


def _ago(days: int) -> date:
    return date.today() - timedelta(days=days)


async def seed(session: AsyncSession) -> bool:
    """Insert demo data if the customers table is empty. Returns True if it seeded."""
    if (await session.scalar(select(func.count()).select_from(Customer))) or 0:
        return False

    pw = hash_password(DEMO_PASSWORD)
    session.add_all(
        [
            Customer(
                id="C001", name="Ayesha Khan", email="ayesha@example.com", plan="Pro", member_since=_ago(420)
            ),
            Customer(
                id="C002", name="Marcus Lee", email="marcus@example.com", plan="Basic", member_since=_ago(60)
            ),
            Customer(
                id="C003",
                name="Sofia Rossi",
                email="sofia@example.com",
                plan="Enterprise",
                member_since=_ago(900),
            ),
        ]
    )
    await session.flush()
    session.add_all(
        [
            User(
                email="ayesha@example.com",
                password_hash=pw,
                role=Role.CUSTOMER,
                display_name="Ayesha Khan",
                customer_id="C001",
            ),
            User(
                email="marcus@example.com",
                password_hash=pw,
                role=Role.CUSTOMER,
                display_name="Marcus Lee",
                customer_id="C002",
            ),
            User(
                email="sofia@example.com",
                password_hash=pw,
                role=Role.CUSTOMER,
                display_name="Sofia Rossi",
                customer_id="C003",
            ),
            User(
                email="agent@nimbus.example",
                password_hash=pw,
                role=Role.AGENT,
                display_name="Jordan (Support)",
            ),
        ]
    )
    session.add_all(
        [
            Order(
                id="ORD-1001",
                customer_id="C001",
                status=OrderStatus.DELIVERED,
                total=Decimal("89.99"),
                items=["Wireless Keyboard"],
                placed_at=_ago(12),
                carrier="DHL",
                tracking_number="DHL123456",
                eta=_ago(7),
                delivered_at=_ago(7),
            ),
            Order(
                id="ORD-1002",
                customer_id="C001",
                status=OrderStatus.IN_TRANSIT,
                total=Decimal("249.00"),
                items=["Noise-Cancelling Headphones"],
                placed_at=_ago(4),
                carrier="FedEx",
                tracking_number="FX998877",
                eta=_ago(-2),
            ),
            Order(
                id="ORD-1003",
                customer_id="C002",
                status=OrderStatus.PROCESSING,
                total=Decimal("34.50"),
                items=["USB-C Cable x3"],
                placed_at=_ago(1),
                eta=_ago(-5),
            ),
            Order(
                id="ORD-1004",
                customer_id="C002",
                status=OrderStatus.DELIVERED,
                total=Decimal("120.00"),
                items=["Desk Lamp"],
                placed_at=_ago(55),
                carrier="UPS",
                tracking_number="1Z999AA1",
                eta=_ago(50),
                delivered_at=_ago(50),
            ),
            Order(
                id="ORD-1005",
                customer_id="C003",
                status=OrderStatus.DELAYED,
                total=Decimal("1499.00"),
                items=["Standing Desk", "Monitor Arm"],
                placed_at=_ago(15),
                carrier="UPS",
                tracking_number="1Z555BB2",
                eta=_ago(-3),
            ),
            Invoice(
                id="INV-2001",
                customer_id="C001",
                amount=Decimal("29.00"),
                status=InvoiceStatus.PAID,
                description="Pro plan - monthly",
                issued_at=_ago(10),
            ),
            Invoice(
                id="INV-2002",
                customer_id="C001",
                amount=Decimal("29.00"),
                status=InvoiceStatus.PAID,
                description="Pro plan - monthly (duplicate charge)",
                issued_at=_ago(10),
            ),
            Invoice(
                id="INV-2003",
                customer_id="C002",
                amount=Decimal("9.00"),
                status=InvoiceStatus.PAID,
                description="Basic plan - monthly",
                issued_at=_ago(45),
            ),
            Invoice(
                id="INV-2004",
                customer_id="C002",
                amount=Decimal("9.00"),
                status=InvoiceStatus.OVERDUE,
                description="Basic plan - monthly",
                issued_at=_ago(15),
            ),
            Invoice(
                id="INV-2005",
                customer_id="C003",
                amount=Decimal("499.00"),
                status=InvoiceStatus.PAID,
                description="Enterprise plan - monthly",
                issued_at=_ago(5),
            ),
        ]
    )
    return True


async def reset(session: AsyncSession) -> None:
    await session.execute(text(f"TRUNCATE {', '.join(BUSINESS_TABLES)} RESTART IDENTITY CASCADE"))


async def _main(do_reset: bool) -> None:
    engine = create_engine(get_settings())
    try:
        async with unit_of_work(create_session_factory(engine)) as s:
            if do_reset:
                await reset(s)
            seeded = await seed(s)
        print("Seeded demo data." if seeded else "Data already present; nothing to do.")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="wipe business data first")
    asyncio.run(_main(parser.parse_args().reset))


if __name__ == "__main__":
    main()
