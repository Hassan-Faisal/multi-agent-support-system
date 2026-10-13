"""Tools available to the specialist agents.

The logged-in customer's id is read from the run config (never from the model),
so a customer can't read or refund someone else's orders by naming their ids.
Business rules (refund limits, return windows) are enforced here in code;
prompts only explain them. (`settings` is app.config; the name `config` is the
RunnableConfig that LangChain injects into each tool call.)
"""
from __future__ import annotations

import json
from datetime import date, datetime

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app import config as settings
from app import db


def _customer_id(cfg: RunnableConfig) -> str:
    cid = (cfg or {}).get("configurable", {}).get("customer_id")
    if not cid:
        raise ValueError("No authenticated customer in this session.")
    return cid


def _days_since(iso: str) -> int:
    return (date.today() - datetime.fromisoformat(iso).date()).days


def _out(obj) -> str:
    return json.dumps(obj, default=str)


# ------------------------------------------------------------------ shared
@tool
def get_customer_profile(config: RunnableConfig) -> str:
    """Get the current customer's profile: name, email, plan and membership date."""
    return _out(db.get_customer(_customer_id(config)))


# ------------------------------------------------------------------ billing
@tool
def list_invoices(config: RunnableConfig) -> str:
    """List the current customer's invoices with amount, status and issue date."""
    return _out(db.get_invoices(_customer_id(config)))


@tool
def request_refund(invoice_id: str, reason: str, config: RunnableConfig, amount: float | None = None) -> str:
    """Request a refund for one of the customer's invoices.

    Args:
        invoice_id: Invoice id, e.g. INV-2002.
        reason: Short reason from the customer, e.g. "duplicate charge".
        amount: Amount to refund. Omit to refund the full invoice.
    """
    cid = _customer_id(config)
    inv = db.get_invoice(invoice_id)
    if not inv or inv["customer_id"] != cid:
        return _out({"ok": False, "error": f"Invoice {invoice_id} not found on this account."})
    if inv["status"] != "paid":
        return _out({"ok": False, "error": f"Invoice is '{inv['status']}', only paid invoices can be refunded."})
    if db.get_refunds_for_invoice(inv["id"]):
        return _out({"ok": False, "error": "A refund already exists for this invoice."})
    amount = round(inv["amount"] if amount is None else float(amount), 2)
    if amount <= 0 or amount > inv["amount"]:
        return _out({"ok": False, "error": f"Amount must be between 0 and {inv['amount']}."})
    age = _days_since(inv["issued_at"])
    window = settings.REFUND_WINDOW_DAYS
    if age > window:
        return _out({"ok": False, "error": f"Invoice is {age} days old; refund window is "
                     f"{window} days. Escalate to a human if the customer disputes this."})
    limit = settings.REFUND_AUTO_APPROVE_LIMIT
    if amount <= limit:
        rf = db.create_refund(inv["id"], cid, amount, reason, "approved")
        return _out({"ok": True, "refund": rf,
                     "note": "Approved automatically. Funds arrive in 5-7 business days."})
    rf = db.create_refund(inv["id"], cid, amount, reason, "pending_approval")
    return _out({"ok": True, "refund": rf,
                 "note": f"Over the ${limit:.0f} auto-approval limit: queued for a human. "
                         "Transfer to escalation so a ticket is created."})



# ------------------------------------------------------------------ orders
@tool
def list_orders(config: RunnableConfig) -> str:
    """List the current customer's orders (id, status, items, total, dates)."""
    return _out(db.get_orders(_customer_id(config)))


@tool
def get_order_status(order_id: str, config: RunnableConfig) -> str:
    """Get status, carrier, tracking number and ETA for one order, e.g. ORD-1002."""
    order = db.get_order(order_id)
    if not order or order["customer_id"] != _customer_id(config):
        return _out({"ok": False, "error": f"Order {order_id} not found on this account."})
    order["returns"] = db.get_returns_for_order(order["id"])
    return _out({"ok": True, "order": order})


@tool
def start_return(order_id: str, reason: str, config: RunnableConfig) -> str:
    """Start a return for a delivered order and email the customer a prepaid label.

    Args:
        order_id: Order id, e.g. ORD-1001.
        reason: Why the customer is returning it.
    """
    cid = _customer_id(config)
    order = db.get_order(order_id)
    if not order or order["customer_id"] != cid:
        return _out({"ok": False, "error": f"Order {order_id} not found on this account."})
    if order["status"] != "delivered":
        return _out({"ok": False, "error": f"Order is '{order['status']}'; only delivered orders can be returned."})
    if db.get_returns_for_order(order["id"]):
        return _out({"ok": False, "error": "A return is already open for this order."})
    window = settings.RETURN_WINDOW_DAYS
    age = _days_since(order["delivered_at"])
    if age > window:
        return _out({"ok": False, "error": f"Delivered {age} days ago; return window is {window} days."})
    rt = db.create_return(order["id"], cid, reason)
    return _out({"ok": True, "return": rt,
                 "note": "Prepaid label emailed. Refund issues once the item is received (3-5 days)."})


# ------------------------------------------------------------------ technical
@tool
def search_knowledge_base(query: str) -> str:
    """Search help-center articles. Use short keyword queries like 'app crash startup'."""
    hits = db.search_kb(query)
    return _out(hits or {"results": [], "note": "No matching articles."})


# ------------------------------------------------------------------ escalation
@tool
def create_support_ticket(category: str, priority: str, summary: str, config: RunnableConfig) -> str:
    """Create a ticket for a human support agent.

    Args:
        category: One of billing, technical, orders, account, other.
        priority: One of low, normal, high, urgent.
        summary: Self-contained summary for the human: issue, what was tried, what the customer wants.
    """
    category = category if category in {"billing", "technical", "orders", "account", "other"} else "other"
    priority = priority if priority in {"low", "normal", "high", "urgent"} else "normal"
    t = db.create_ticket(_customer_id(config), category, priority, summary)
    return _out({"ok": True, "ticket": t, "note": "A human agent will reply by email within 24 hours "
                 "(4 hours for high/urgent)."})


# ------------------------------------------------------------------ handoffs
AGENT_DESCRIPTIONS = {
    "billing": "invoices, charges, payments, plans and refunds",
    "technical": "bugs, login/password, app crashes, sync, API and how-to questions",
    "orders": "order status, shipping, tracking, delivery problems and returns",
    "escalation": "a human agent: angry customers, legal/security issues, requests outside policy, "
                  "or anything the other agents can't resolve",
}

HANDOFF_PREFIX = "transfer_to_"


def make_handoff_tool(target: str):
    @tool(f"{HANDOFF_PREFIX}{target}")
    def handoff(reason: str) -> str:
        """placeholder"""
        return f"Transferred to {target} agent. Reason: {reason}"

    handoff.description = (
        f"Transfer the conversation to the {target} agent, who handles {AGENT_DESCRIPTIONS[target]}. "
        "Call this alone (no other tools in the same turn) and don't write a reply yourself; "
        "the next agent will respond. `reason` is a one-line note for them."
    )
    return handoff


SPECIALIST_TOOLS = {
    "billing": [get_customer_profile, list_invoices, request_refund],
    "technical": [get_customer_profile, search_knowledge_base],
    "orders": [get_customer_profile, list_orders, get_order_status, start_return],
    "escalation": [get_customer_profile, create_support_ticket],
}
