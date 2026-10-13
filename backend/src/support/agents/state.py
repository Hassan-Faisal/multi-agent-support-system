from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

AGENTS: tuple[str, ...] = ("billing", "technical", "orders", "escalation")
RESET = "__reset__"

TraceEvent = dict[str, Any]


def merge_events(left: list[TraceEvent] | None, right: list[TraceEvent] | None) -> list[TraceEvent]:
    """Append reducer with a reset marker, so the trace holds only the current turn
    instead of growing forever in the checkpoint."""
    right = right or []
    if right and right[0].get("type") == RESET:
        return list(right[1:])
    return [*(left or []), *right]


class SupportState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    active_agent: str | None
    handoffs: int
    steps: int
    events: Annotated[list[TraceEvent], merge_events]


class RouteDecision(BaseModel):
    """Which specialist should handle the customer's latest message."""

    agent: Literal["billing", "technical", "orders", "escalation", "none"] = Field(
        description="Specialist to route to, or 'none' for greetings/small talk only."
    )
    reason: str = Field(description="One short sentence explaining the choice.")
    reply: str | None = Field(default=None, description="Short friendly reply, only when agent is 'none'.")
