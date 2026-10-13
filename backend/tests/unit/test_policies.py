from datetime import date, timedelta
from decimal import Decimal

import pytest

from support.domain.enums import InvoiceStatus, OrderStatus
from support.domain.errors import PolicyViolation
from support.domain.policies import RefundPolicy, ReturnPolicy, check_return_allowed, decide_refund

TODAY = date(2026, 10, 13)
POLICY = RefundPolicy(auto_approve_limit=Decimal("50.00"), window_days=30)


def refund(**overrides):  # type: ignore[no-untyped-def]
    args = dict(
        invoice_amount=Decimal("29.00"),
        invoice_status=InvoiceStatus.PAID,
        issued_at=TODAY - timedelta(days=10),
        has_existing_refund=False,
        requested_amount=None,
        today=TODAY,
        policy=POLICY,
    )
    return decide_refund(**{**args, **overrides})


def test_full_refund_under_limit_is_auto_approved() -> None:
    d = refund()
    assert d.amount == Decimal("29.00") and d.auto_approve


def test_over_limit_needs_human() -> None:
    d = refund(invoice_amount=Decimal("499.00"))
    assert not d.auto_approve


def test_limit_is_inclusive() -> None:
    assert refund(invoice_amount=Decimal("50.00")).auto_approve
    assert not refund(invoice_amount=Decimal("50.01")).auto_approve


def test_partial_refund_is_rounded_to_cents() -> None:
    assert refund(requested_amount=Decimal("10.005")).amount == Decimal("10.01")


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"invoice_status": InvoiceStatus.OVERDUE}, "Only paid invoices"),
        ({"has_existing_refund": True}, "already exists"),
        ({"requested_amount": Decimal("0")}, "greater than 0"),
        ({"requested_amount": Decimal("29.01")}, "at most"),
        ({"issued_at": TODAY - timedelta(days=31)}, "refund window"),
    ],
)
def test_refund_violations(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(PolicyViolation, match=message):
        refund(**overrides)


def test_refund_window_boundary_is_inclusive() -> None:
    assert refund(issued_at=TODAY - timedelta(days=30)).auto_approve


def test_return_rules() -> None:
    policy = ReturnPolicy(window_days=30)
    ok = dict(
        order_status=OrderStatus.DELIVERED,
        delivered_at=TODAY - timedelta(days=5),
        has_existing_return=False,
        today=TODAY,
        policy=policy,
    )
    check_return_allowed(**ok)  # type: ignore[arg-type]
    with pytest.raises(PolicyViolation, match="in transit"):
        check_return_allowed(**{**ok, "order_status": OrderStatus.IN_TRANSIT, "delivered_at": None})  # type: ignore[arg-type]
    with pytest.raises(PolicyViolation, match="already open"):
        check_return_allowed(**{**ok, "has_existing_return": True})  # type: ignore[arg-type]
    with pytest.raises(PolicyViolation, match="50 days ago"):
        check_return_allowed(**{**ok, "delivered_at": TODAY - timedelta(days=50)})  # type: ignore[arg-type]
