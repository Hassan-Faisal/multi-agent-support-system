"""Business policy as pure functions: no I/O, no clock, trivially unit-testable.

These are the rules the agents must never be able to talk their way around, which
is why they live here and are enforced by the services rather than in prompts.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from support.domain.enums import InvoiceStatus, OrderStatus
from support.domain.errors import PolicyViolation

CENT = Decimal("0.01")


@dataclass(frozen=True)
class RefundPolicy:
    auto_approve_limit: Decimal
    window_days: int


@dataclass(frozen=True)
class RefundDecision:
    amount: Decimal
    auto_approve: bool


def decide_refund(
    *,
    invoice_amount: Decimal,
    invoice_status: InvoiceStatus,
    issued_at: date,
    has_existing_refund: bool,
    requested_amount: Decimal | None,
    today: date,
    policy: RefundPolicy,
) -> RefundDecision:
    if invoice_status != InvoiceStatus.PAID:
        raise PolicyViolation(f"Only paid invoices can be refunded; this invoice is {invoice_status.value}.")
    if has_existing_refund:
        raise PolicyViolation("A refund already exists for this invoice.")
    amount = (invoice_amount if requested_amount is None else requested_amount).quantize(CENT, ROUND_HALF_UP)
    if amount <= 0 or amount > invoice_amount:
        raise PolicyViolation(f"Refund amount must be greater than 0 and at most {invoice_amount}.")
    age = (today - issued_at).days
    if age > policy.window_days:
        raise PolicyViolation(
            f"This invoice is {age} days old and the refund window is {policy.window_days} days."
        )
    return RefundDecision(amount=amount, auto_approve=amount <= policy.auto_approve_limit)


@dataclass(frozen=True)
class ReturnPolicy:
    window_days: int


def check_return_allowed(
    *,
    order_status: OrderStatus,
    delivered_at: date | None,
    has_existing_return: bool,
    today: date,
    policy: ReturnPolicy,
) -> None:
    if order_status != OrderStatus.DELIVERED or delivered_at is None:
        raise PolicyViolation(
            f"Only delivered orders can be returned; this order is {order_status.value.replace('_', ' ')}."
        )
    if has_existing_return:
        raise PolicyViolation("A return is already open for this order.")
    age = (today - delivered_at).days
    if age > policy.window_days:
        raise PolicyViolation(
            f"This order was delivered {age} days ago and the return window is {policy.window_days} days."
        )
