"""Agent tools: thin adapters from LLM tool calls to the service layer.

Security model:
- The customer id and conversation id come from the run config, set by the API from
  the authenticated principal. They are never tool arguments, so the model can't be
  talked into acting on another account.
- Every side effect goes through a service that enforces policy, locks rows and
  writes the audit log. Tools only translate inputs/outputs.
- Domain errors become structured results the model can explain; unexpected errors
  propagate and are handled (and logged) by the graph.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool, tool
from pydantic import BaseModel

from support.db.session import SessionFactory, unit_of_work
from support.domain.enums import TicketCategory, TicketPriority
from support.domain.errors import DomainError
from support.domain.policies import RefundPolicy, ReturnPolicy
from support.rag.retriever import HybridRetriever, format_for_model
from support.services.billing import BillingService
from support.services.customers import CustomerService
from support.services.orders import OrderService
from support.services.tickets import TicketService

HANDOFF_PREFIX = "transfer_to_"
KB_TOOL = "search_help_center"

AGENT_DESCRIPTIONS = {
    "billing": "invoices, charges, payments, plans and refunds",
    "technical": "sign-in, passwords, 2FA, crashes, sync, the API and how-to questions",
    "orders": "order status, shipping, tracking, delivery problems, returns and warranty",
    "escalation": "human staff: requests for a person, angry customers, legal or security issues, "
    "policy exceptions, or anything the other agents can't resolve",
}


@dataclass(frozen=True)
class AgentDeps:
    sessions: SessionFactory
    retriever: HybridRetriever
    refund_policy: RefundPolicy
    return_policy: ReturnPolicy
    retrieval_top_k: int = 4


@dataclass(frozen=True)
class RunContext:
    customer_id: str
    conversation_id: uuid.UUID | None

    @classmethod
    def from_config(cls, config: RunnableConfig) -> RunContext:
        conf = (config or {}).get("configurable", {})
        cid = conf.get("customer_id")
        if not cid:
            raise PermissionError("no authenticated customer in run config")
        conv = conf.get("conversation_id")
        return cls(customer_id=cid, conversation_id=uuid.UUID(str(conv)) if conv else None)


def _json(payload: Any) -> str:
    def default(o: Any) -> Any:
        if isinstance(o, BaseModel):
            return o.model_dump(mode="json")
        return str(o)

    return json.dumps(payload, default=default)


def _error(e: DomainError) -> str:
    return _json({"ok": False, "error": e.code, "message": e.message})


def build_agent_tools(deps: AgentDeps, agent: str) -> list[BaseTool]:
    """Tools for one specialist. `agent` is recorded as the actor in the audit log."""
    actor = f"agent:{agent}"
    s = deps.sessions

    @tool
    async def get_customer_profile(config: RunnableConfig) -> str:
        """Get the signed-in customer's profile: name, email, plan and member-since date."""
        ctx = RunContext.from_config(config)
        async with unit_of_work(s) as session:
            return _json(await CustomerService(session).get(ctx.customer_id))

    async def _search(query: str) -> tuple[str, list[dict[str, str]]]:
        chunks = await deps.retriever.search(query, top_k=deps.retrieval_top_k)
        seen: dict[str, dict[str, str]] = {}
        for c in chunks:
            seen.setdefault(c.slug, {"source": c.slug, "title": c.title, "url": c.url})
        return format_for_model(chunks), list(seen.values())

    search_help_center = StructuredTool.from_function(
        coroutine=_search,
        name=KB_TOOL,
        description=(
            "Search Nimbus help-center articles for how-to steps, troubleshooting and policies "
            "(refunds, returns, plans, shipping, security). Pass the customer's question in "
            "plain words."
        ),
        response_format="content_and_artifact",
    )

    # ------------------------------------------------------------ billing
    @tool
    async def list_invoices(config: RunnableConfig) -> str:
        """List the customer's invoices with amount, status, issue date and any refunds."""
        ctx = RunContext.from_config(config)
        async with unit_of_work(s) as session:
            return _json(await BillingService(session, deps.refund_policy).list_invoices(ctx.customer_id))

    @tool
    async def request_refund(
        invoice_id: str, reason: str, config: RunnableConfig, amount: float | None = None
    ) -> str:
        """Refund one of the customer's invoices. Small refunds are approved instantly; larger ones
        become pending with a ticket for the billing team.

        Args:
            invoice_id: Invoice id, e.g. INV-2002.
            reason: The customer's reason in a few words, e.g. "duplicate charge".
            amount: Amount to refund. Omit for the full invoice amount.
        """
        ctx = RunContext.from_config(config)
        try:
            dec = None if amount is None else Decimal(str(amount))
        except InvalidOperation:
            return _json({"ok": False, "error": "invalid_amount", "message": "Amount must be a number."})
        try:
            async with unit_of_work(s) as session:
                result = await BillingService(session, deps.refund_policy).request_refund(
                    customer_id=ctx.customer_id,
                    invoice_id=invoice_id,
                    reason=reason,
                    amount=dec,
                    actor=actor,
                    conversation_id=ctx.conversation_id,
                )
        except DomainError as e:
            return _error(e)
        note = (
            "Approved. Funds return to the original payment method in 5-7 business days."
            if result.auto_approved
            else "Pending approval by the billing team (usually within 4 business hours). "
            "A ticket has been opened; the customer will get an email with the decision."
        )
        return _json({"ok": True, **result.model_dump(mode="json"), "note": note})

    # ------------------------------------------------------------ orders
    @tool
    async def list_orders(config: RunnableConfig) -> str:
        """List the customer's orders: id, status, items, total and key dates."""
        ctx = RunContext.from_config(config)
        async with unit_of_work(s) as session:
            return _json(await OrderService(session, deps.return_policy).list_orders(ctx.customer_id))

    @tool
    async def get_order_status(order_id: str, config: RunnableConfig) -> str:
        """Get status, carrier, tracking number, ETA and returns for one order, e.g. ORD-1002."""
        ctx = RunContext.from_config(config)
        try:
            async with unit_of_work(s) as session:
                order = await OrderService(session, deps.return_policy).get_order(ctx.customer_id, order_id)
        except DomainError as e:
            return _error(e)
        return _json({"ok": True, "order": order})

    @tool
    async def start_return(order_id: str, reason: str, config: RunnableConfig) -> str:
        """Start a return for a delivered order; a prepaid label is emailed to the customer.

        Args:
            order_id: Order id, e.g. ORD-1001.
            reason: Why the customer is returning it.
        """
        ctx = RunContext.from_config(config)
        try:
            async with unit_of_work(s) as session:
                ret = await OrderService(session, deps.return_policy).start_return(
                    customer_id=ctx.customer_id, order_id=order_id, reason=reason, actor=actor
                )
        except DomainError as e:
            return _error(e)
        return _json(
            {
                "ok": True,
                "return": ret,
                "note": "Prepaid label emailed. Refund is issued 3-5 "
                "business days after the warehouse receives the item.",
            }
        )

    # ------------------------------------------------------------ escalation
    @tool
    async def create_support_ticket(
        category: Literal["billing", "technical", "orders", "account", "other"],
        priority: Literal["low", "normal", "high", "urgent"],
        summary: str,
        config: RunnableConfig,
    ) -> str:
        """Open a ticket for human support staff (or return the one already open for this conversation).

        Args:
            category: billing, technical, orders, account or other.
            priority: urgent = security/fraud/legal; high = money owed or very upset; else normal/low.
            summary: Self-contained summary for staff: the issue, what was tried, what the customer wants.
        """
        ctx = RunContext.from_config(config)
        async with unit_of_work(s) as session:
            ticket, created = await TicketService(session).create(
                customer_id=ctx.customer_id,
                category=TicketCategory(category),
                priority=TicketPriority(priority),
                summary=summary,
                actor=actor,
                conversation_id=ctx.conversation_id,
            )
        sla = "4 hours" if ticket.priority in ("high", "urgent") else "24 hours"
        return _json(
            {
                "ok": True,
                "ticket": ticket,
                "already_existed": not created,
                "note": f"A support specialist will reply by email within {sla}.",
            }
        )

    per_agent: dict[str, list[BaseTool]] = {
        "billing": [get_customer_profile, list_invoices, request_refund, search_help_center],
        "technical": [get_customer_profile, search_help_center],
        "orders": [get_customer_profile, list_orders, get_order_status, start_return, search_help_center],
        "escalation": [get_customer_profile, create_support_ticket],
    }
    return per_agent[agent] + [make_handoff_tool(t) for t in AGENT_DESCRIPTIONS if t != agent]


def make_handoff_tool(target: str) -> BaseTool:
    async def handoff(reason: str) -> str:
        return f"Transferred to the {target} agent."

    return StructuredTool.from_function(
        coroutine=handoff,
        name=f"{HANDOFF_PREFIX}{target}",
        description=(
            f"Transfer the conversation to the {target} agent, who handles {AGENT_DESCRIPTIONS[target]}. "
            "Call it on its own and don't write a reply; the next agent will answer. "
            "`reason` is a one-line note for them."
        ),
    )
