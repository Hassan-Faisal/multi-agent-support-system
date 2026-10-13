"""Deterministic checks for agent eval cases. Pure functions over a run transcript."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field


class Expect(BaseModel):
    route: Literal["billing", "technical", "orders", "escalation", "none", "off_topic"] | None = None
    agents: list[str] = []
    final_agent: str | None = None
    tools: list[str] = []
    no_tools: list[str] = []
    reply_any: list[str] = []
    reply_none: list[str] = []
    refund: dict[str, str] = {}
    return_created: dict[str, bool] = {}
    min_tickets: int | None = None


class Case(BaseModel):
    id: str
    customer: str
    turns: list[str] = Field(min_length=1)
    expect: Expect


@dataclass
class RunRecord:
    """What happened during one case, gathered by the runner."""

    route: str | None
    agents: set[str]
    final_agent: str | None
    tools: list[str]
    final_reply: str
    refunds: dict[str, str]  # invoice id -> status
    returns: set[str]  # order ids with a return
    tickets: int
    error: str | None = None


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class CaseResult:
    case: Case
    record: RunRecord
    checks: list[CheckResult] = field(default_factory=list)
    judge: dict[str, object] | None = None

    @property
    def passed(self) -> bool:
        return self.record.error is None and all(c.passed for c in self.checks)


def evaluate(case: Case, r: RunRecord) -> list[CheckResult]:
    e, out = case.expect, []
    reply = r.final_reply.lower()

    if r.error:
        return [CheckResult("run", False, r.error)]
    if e.route is not None:
        out.append(CheckResult("route", r.route == e.route, f"expected {e.route}, got {r.route}"))
    for a in e.agents:
        out.append(CheckResult(f"agent:{a}", a in r.agents, f"agents involved: {sorted(r.agents)}"))
    if e.final_agent:
        out.append(
            CheckResult(
                "final_agent",
                r.final_agent == e.final_agent,
                f"expected {e.final_agent}, got {r.final_agent}",
            )
        )
    for t in e.tools:
        out.append(CheckResult(f"tool:{t}", t in r.tools, f"tools called: {r.tools}"))
    for t in e.no_tools:
        out.append(CheckResult(f"no_tool:{t}", t not in r.tools, f"tools called: {r.tools}"))
    if e.reply_any:
        hit = any(s.lower() in reply for s in e.reply_any)
        out.append(CheckResult("reply_any", hit, f"none of {e.reply_any} in reply"))
    for s in e.reply_none:
        out.append(CheckResult(f"reply_none:{s}", s.lower() not in reply, f"reply contains {s!r}"))
    for inv, status in e.refund.items():
        got = r.refunds.get(inv, "none")
        out.append(CheckResult(f"refund:{inv}", got == status, f"expected {status}, got {got}"))
    for order, created in e.return_created.items():
        has_return = order in r.returns
        out.append(
            CheckResult(f"return:{order}", has_return == created, f"expected {created}, got {has_return}")
        )
    if e.min_tickets is not None:
        out.append(CheckResult("tickets", r.tickets >= e.min_tickets, f"{r.tickets} ticket(s)"))
    return out


# Which checks feed which headline metric.
CATEGORIES = {
    "routing": ("route", "agent:", "final_agent"),
    "tool_use": ("tool:", "no_tool:"),
    "policy_and_safety": ("refund:", "return:", "tickets", "reply_none:"),
    "answer_content": ("reply_any",),
}


def category_scores(results: list[CaseResult]) -> dict[str, tuple[int, int]]:
    scores = {k: [0, 0] for k in CATEGORIES}
    for res in results:
        for c in res.checks:
            for cat, prefixes in CATEGORIES.items():
                if c.name.startswith(prefixes):
                    scores[cat][1] += 1
                    scores[cat][0] += int(c.passed)
    return {k: (v[0], v[1]) for k, v in scores.items()}
