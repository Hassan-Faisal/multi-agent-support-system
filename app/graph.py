"""LangGraph orchestration for the multi-agent support system.

    START ─▶ entry ─┬─(no active agent)─▶ triage ─┬─▶ <specialist> ⇄ <specialist>_tools
                    │                              └─▶ END (small talk)
                    └─(active agent)──────────────────▶ <specialist>

Each specialist is an LLM node plus a tools node. A specialist finishes the turn
when it replies without tool calls. It can hand the conversation to another
specialist via a transfer_to_* tool. The active agent is "sticky": the next
customer message goes straight to whoever handled the last one, skipping triage.

Guardrails: max handoffs per turn (prevents ping-pong) and max tool steps per
agent per turn (prevents loops); both fall back to the escalation agent.
"""
from __future__ import annotations

import operator
from datetime import date
from typing import Annotated, Literal, Optional, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Command
from pydantic import BaseModel, Field

from app import config as settings
from app import db, prompts
from app.tools import HANDOFF_PREFIX, SPECIALIST_TOOLS, make_handoff_tool

AGENTS = list(SPECIALIST_TOOLS)  # ["billing", "technical", "orders", "escalation"]
AgentName = Literal["billing", "technical", "orders", "escalation"]


class SupportState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    active_agent: Optional[str]
    handoffs: int            # handoffs during the current turn
    steps: int               # tool rounds by the current agent during this turn
    events: Annotated[list[dict], operator.add]  # audit trail of routing decisions


class RouteDecision(BaseModel):
    """Which specialist should handle the customer's latest message."""
    agent: Literal["billing", "technical", "orders", "escalation", "none"] = Field(
        description="Specialist to route to, or 'none' for greetings/small talk.")
    reply: Optional[str] = Field(default=None, description="Short reply, only when agent is 'none'.")
    reason: str = Field(description="One short sentence explaining the choice.")


def _event(kind: str, **data) -> dict:
    return {"type": kind, **data}


def _system_prompt(agent: str, cfg: RunnableConfig) -> str:
    cid = cfg.get("configurable", {}).get("customer_id", "unknown")
    cust = db.get_customer(cid) or {}
    shared = prompts.SHARED.format(
        customer_name=cust.get("name", "Unknown"), customer_id=cid,
        plan=cust.get("plan", "unknown"), today=date.today().isoformat())
    return f"{shared}\n\n{prompts.SPECIALISTS[agent]}"


def build_graph(llm=None, triage_llm=None, checkpointer=None):
    """Compile the support graph.

    `llm` / `triage_llm` are chat models; pass fakes in tests. If omitted they're
    created from SUPPORT_MODEL / SUPPORT_TRIAGE_MODEL via init_chat_model.
    """
    if llm is None or triage_llm is None:
        from langchain.chat_models import init_chat_model
        llm = llm or init_chat_model(settings.MODEL, temperature=0)
        triage_llm = triage_llm or init_chat_model(settings.TRIAGE_MODEL, temperature=0)

    # Native JSON-schema structured output; newer Claude models don't support the
    # forced-tool-call method. Fall back to the provider default if unsupported.
    try:
        router = triage_llm.with_structured_output(RouteDecision, method="json_schema")
    except (ValueError, NotImplementedError, TypeError):
        router = triage_llm.with_structured_output(RouteDecision)

    # Every specialist gets its own tools plus transfers to every *other* specialist.
    agent_tools = {
        name: tools + [make_handoff_tool(t) for t in AGENTS if t != name]
        for name, tools in SPECIALIST_TOOLS.items()
    }
    bound = {name: llm.bind_tools(tools) for name, tools in agent_tools.items()}
    tool_maps = {name: {t.name: t for t in tools} for name, tools in agent_tools.items()}

    # ---------------------------------------------------------------- nodes
    def entry(state: SupportState) -> Command:
        reset = {"handoffs": 0, "steps": 0}
        target = state.get("active_agent")
        return Command(goto=target if target in AGENTS else "triage", update=reset)

    def triage(state: SupportState) -> Command:
        decision: RouteDecision = router.invoke(
            [SystemMessage(prompts.TRIAGE), *state["messages"]])
        ev = _event("route", agent=decision.agent, reason=decision.reason)
        if decision.agent == "none":
            reply = decision.reply or "Hi! How can I help you today?"
            return Command(goto=END, update={
                "messages": [AIMessage(reply, name="triage")], "events": [ev]})
        return Command(goto=decision.agent, update={"active_agent": decision.agent, "events": [ev]})

    def make_agent_node(name: str):
        def agent_node(state: SupportState, config: RunnableConfig) -> Command:
            msgs = [SystemMessage(_system_prompt(name, config)), *state["messages"]]
            response = bound[name].invoke(msgs, config)
            response.name = name
            nxt = f"{name}_tools" if response.tool_calls else END
            return Command(goto=nxt, update={"messages": [response]})
        agent_node.__name__ = name
        return agent_node

    def make_tools_node(name: str):
        def tools_node(state: SupportState, config: RunnableConfig) -> Command:
            last: AIMessage = state["messages"][-1]
            results, events, handoff_to = [], [], None
            for call in last.tool_calls:
                tool = tool_maps[name].get(call["name"])
                if tool is None:
                    out = f"Error: tool '{call['name']}' is not available to the {name} agent."
                else:
                    try:
                        out = tool.invoke(call["args"], config)
                    except Exception as e:  # surface tool errors to the model, don't crash
                        out = f"Error: {type(e).__name__}: {e}"
                results.append(ToolMessage(str(out), tool_call_id=call["id"], name=call["name"]))
                if call["name"].startswith(HANDOFF_PREFIX):
                    handoff_to = handoff_to or call["name"][len(HANDOFF_PREFIX):]
                    events.append(_event("handoff", source=name, target=handoff_to,
                                         reason=call["args"].get("reason", "")))
                else:
                    events.append(_event("tool", agent=name, tool=call["name"], args=call["args"]))

            update = {"messages": results, "events": events}
            if handoff_to:
                handoffs = state.get("handoffs", 0) + 1
                if handoffs > settings.MAX_HANDOFFS_PER_TURN and handoff_to != "escalation":
                    events.append(_event("guardrail", detail="too many handoffs; escalating"))
                    handoff_to = "escalation"
                update.update(active_agent=handoff_to, handoffs=handoffs, steps=0)
                return Command(goto=handoff_to, update=update)

            steps = state.get("steps", 0) + 1
            update["steps"] = steps
            if steps >= settings.MAX_TOOL_STEPS_PER_AGENT and name != "escalation":
                events.append(_event("guardrail", detail=f"{name} hit tool-step limit; escalating"))
                update.update(active_agent="escalation", steps=0)
                return Command(goto="escalation", update=update)
            return Command(goto=name, update=update)
        tools_node.__name__ = f"{name}_tools"
        return tools_node

    # ---------------------------------------------------------------- wiring
    g = StateGraph(SupportState)
    g.add_node("entry", entry, destinations=("triage", *AGENTS))
    g.add_node("triage", triage, destinations=(*AGENTS, END))
    for name in AGENTS:
        g.add_node(name, make_agent_node(name), destinations=(f"{name}_tools", END))
        g.add_node(f"{name}_tools", make_tools_node(name), destinations=tuple(AGENTS))
    g.add_edge(START, "entry")

    return g.compile(checkpointer=checkpointer if checkpointer is not None else MemorySaver())
