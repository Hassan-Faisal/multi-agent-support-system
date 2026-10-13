"""LangGraph orchestration.

    START → guard ─┬─ blocked ───────────────────────────────▶ END (refusal)
                   └─ entry ─┬─ no active agent → triage ─┬─▶ END (small talk)
                             │                            ▼
                             └─ active agent ──────▶ <specialist> ⇄ <specialist>_tools
                                                         │  transfer_to_* → other specialist
                                                         └─ reply → END

- guard: PII redaction + prompt-injection screen on the new customer message.
- triage: cheap model, structured output, only on the first message of a topic;
  afterwards the conversation is "sticky" to the active specialist.
- specialists: LLM + tools loop. Handoffs switch agent within the same turn.
- guardrails: handoff cap and per-agent tool-step cap both fall back to escalation.

Every routing decision, tool call and guardrail trip is a trace event, persisted in
state for the current turn and streamed live via the "custom" stream mode.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from datetime import date
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import Runnable, RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from support.agents import prompts
from support.agents.state import AGENTS, RESET, RouteDecision, SupportState, TraceEvent
from support.agents.tools import HANDOFF_PREFIX, KB_TOOL, AgentDeps, RunContext, build_agent_tools
from support.db.session import unit_of_work
from support.observability.logs import get_logger
from support.observability.metrics import GUARDRAILS, HANDOFFS, LLM_TOKENS, ROUTES, TOOL_CALLS
from support.security.injection import score_injection
from support.security.pii import redact_pii
from support.services.customers import CustomerService

log = get_logger(__name__)


class GraphLimits:
    def __init__(
        self,
        max_handoffs: int = 3,
        max_tool_steps: int = 8,
        max_context_messages: int = 40,
        injection_threshold: float = 0.8,
    ) -> None:
        self.max_handoffs, self.max_tool_steps = max_handoffs, max_tool_steps
        self.max_context_messages, self.injection_threshold = max_context_messages, injection_threshold


def text_of(message: AnyMessage) -> str:
    """Plain text of a message whose content may be a string or provider content blocks."""
    c = message.content
    if isinstance(c, str):
        return c
    return "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in c)


def context_window(messages: Sequence[AnyMessage], limit: int) -> list[AnyMessage]:
    """Last `limit` messages, never starting mid tool-exchange (providers reject a tool
    result without its call), so the window always begins at a customer message."""
    window = list(messages[-limit:])
    while window and not isinstance(window[0], HumanMessage):
        window.pop(0)
    return window or list(messages[-1:])


def build_graph(
    *,
    deps: AgentDeps,
    llm: BaseChatModel,
    triage_llm: BaseChatModel,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    limits: GraphLimits | None = None,
) -> CompiledStateGraph[Any, Any, Any, Any]:
    limits = limits or GraphLimits()

    router: Runnable[Any, Any]
    try:  # native JSON-schema output; newer Claude models don't support forced tool calls
        router = triage_llm.with_structured_output(RouteDecision, method="json_schema")
    except (ValueError, NotImplementedError, TypeError):
        router = triage_llm.with_structured_output(RouteDecision)

    tools: dict[str, dict[str, BaseTool]] = {}
    bound: dict[str, Runnable[Any, Any]] = {}
    for name in AGENTS:
        agent_tools = build_agent_tools(deps, name)
        tools[name] = {t.name: t for t in agent_tools}
        bound[name] = llm.bind_tools(agent_tools)

    def emit(*events: TraceEvent) -> list[TraceEvent]:
        writer = get_stream_writer()
        for e in events:
            writer({"trace": e})
        return list(events)

    async def system_prompt(agent: str, config: RunnableConfig) -> str:
        ctx = RunContext.from_config(config)
        async with unit_of_work(deps.sessions) as s:
            cust = await CustomerService(s).get(ctx.customer_id)
        shared = prompts.SHARED.format(
            customer_name=cust.name, customer_id=cust.id, plan=cust.plan, today=date.today().isoformat()
        )
        return f"{shared}\n\n{prompts.SPECIALISTS[agent]}"

    # ------------------------------------------------------------------ nodes
    async def guard(state: SupportState) -> Command[Any]:
        last = state["messages"][-1]
        reset: list[TraceEvent] = [{"type": RESET}]
        if not isinstance(last, HumanMessage):
            return Command(goto="entry", update={"events": reset})

        redaction = redact_pii(text_of(last))
        verdict = score_injection(redaction.text)
        events: list[TraceEvent] = []
        update: dict[str, Any] = {}
        if redaction.changed:
            GUARDRAILS.labels("pii_redacted").inc()
            events.append(
                {"type": "guardrail", "kind": "pii_redacted", "detail": sorted(set(redaction.findings))}
            )
            update["messages"] = [HumanMessage(redaction.text, id=last.id)]  # replaces the original
        if verdict.blocked(limits.injection_threshold):
            GUARDRAILS.labels("injection_blocked").inc()
            events.append({"type": "guardrail", "kind": "injection_blocked", "score": verdict.score})
            log.warning("guard.injection_blocked", score=verdict.score, signals=verdict.signals)
            update["messages"] = [
                *update.get("messages", []),
                AIMessage(prompts.GUARDRAIL_REFUSAL, name="guardrail"),
            ]
            return Command(goto=END, update={**update, "events": reset + emit(*events)})
        if verdict.score > 0:
            events.append({"type": "guardrail", "kind": "injection_suspected", "score": verdict.score})
        return Command(goto="entry", update={**update, "events": reset + emit(*events)})

    def entry(state: SupportState) -> Command[Any]:
        target = state.get("active_agent")
        return Command(goto=target if target in AGENTS else "triage", update={"handoffs": 0, "steps": 0})

    async def triage(state: SupportState, config: RunnableConfig) -> Command[Any]:
        msgs = context_window(state["messages"], 10)
        raw = await router.ainvoke([SystemMessage(prompts.TRIAGE), *msgs], config)
        decision = RouteDecision.model_validate(raw)
        ROUTES.labels(decision.agent).inc()
        ev = emit({"type": "route", "agent": decision.agent, "reason": decision.reason})
        if decision.agent == "none":
            reply = decision.reply or "Hi! How can I help you today?"
            return Command(goto=END, update={"messages": [AIMessage(reply, name="triage")], "events": ev})
        return Command(goto=decision.agent, update={"active_agent": decision.agent, "events": ev})

    def make_agent(name: str) -> Any:
        async def agent_node(state: SupportState, config: RunnableConfig) -> Command[Any]:
            sys = SystemMessage(await system_prompt(name, config))
            msgs = context_window(state["messages"], limits.max_context_messages)
            response: AIMessage = await bound[name].ainvoke([sys, *msgs], config)
            response.name = name
            if response.usage_metadata:
                LLM_TOKENS.labels(name, "input").inc(response.usage_metadata["input_tokens"])
                LLM_TOKENS.labels(name, "output").inc(response.usage_metadata["output_tokens"])
            if response.tool_calls:
                return Command(goto=f"{name}_tools", update={"messages": [response]})
            response.response_metadata["sources"] = _cited_sources(state["messages"], text_of(response))
            return Command(goto=END, update={"messages": [response]})

        agent_node.__name__ = name
        return agent_node

    def make_tools(name: str) -> Any:
        async def tools_node(state: SupportState, config: RunnableConfig) -> Command[Any]:
            last = state["messages"][-1]
            assert isinstance(last, AIMessage)
            results: list[ToolMessage] = []
            events: list[TraceEvent] = []
            handoff_to: str | None = None

            for call in last.tool_calls:
                started = time.perf_counter()
                tool = tools[name].get(call["name"])
                outcome = "ok"
                if tool is None:
                    msg = ToolMessage(
                        f"Error: tool {call['name']!r} is not available to the {name} agent.",
                        tool_call_id=call["id"],
                        name=call["name"],
                        status="error",
                    )
                    outcome = "unknown_tool"
                else:
                    try:
                        msg = await tool.ainvoke({**call, "type": "tool_call"}, config)
                    except Exception as e:  # never crash the turn on a tool failure
                        log.exception("tool.failed", agent=name, tool=call["name"])
                        msg = ToolMessage(
                            "Error: the tool failed unexpectedly. Apologize and offer to "
                            "escalate to a human.",
                            tool_call_id=call["id"],
                            name=call["name"],
                            status="error",
                        )
                        outcome = f"exception:{type(e).__name__}"
                    if '"ok": false' in text_of(msg):
                        outcome = "rejected"
                results.append(msg)
                TOOL_CALLS.labels(name, call["name"], outcome.split(":")[0]).inc()

                if call["name"].startswith(HANDOFF_PREFIX):
                    handoff_to = handoff_to or call["name"].removeprefix(HANDOFF_PREFIX)
                    events.append(
                        {
                            "type": "handoff",
                            "source": name,
                            "target": handoff_to,
                            "reason": call["args"].get("reason", ""),
                        }
                    )
                else:
                    events.append(
                        {
                            "type": "tool",
                            "agent": name,
                            "tool": call["name"],
                            "args": call["args"],
                            "outcome": outcome,
                            "ms": round((time.perf_counter() - started) * 1000),
                        }
                    )
                    if call["name"] == KB_TOOL and getattr(msg, "artifact", None):
                        events.append({"type": "sources", "agent": name, "sources": msg.artifact})

            update: dict[str, Any] = {"messages": results}
            if handoff_to:
                handoffs = state.get("handoffs", 0) + 1
                if handoffs > limits.max_handoffs and handoff_to != "escalation":
                    GUARDRAILS.labels("handoff_limit").inc()
                    events.append(
                        {
                            "type": "guardrail",
                            "kind": "handoff_limit",
                            "detail": f"{handoffs} handoffs this turn; escalating",
                        }
                    )
                    handoff_to = "escalation"
                HANDOFFS.labels(name, handoff_to).inc()
                update |= {
                    "active_agent": handoff_to,
                    "handoffs": handoffs,
                    "steps": 0,
                    "events": emit(*events),
                }
                return Command(goto=handoff_to, update=update)

            steps = state.get("steps", 0) + 1
            if steps >= limits.max_tool_steps and name != "escalation":
                GUARDRAILS.labels("tool_step_limit").inc()
                events.append(
                    {
                        "type": "guardrail",
                        "kind": "tool_step_limit",
                        "detail": f"{name} used {steps} tool rounds; escalating",
                    }
                )
                update |= {"active_agent": "escalation", "steps": 0, "events": emit(*events)}
                return Command(goto="escalation", update=update)
            update |= {"steps": steps, "events": emit(*events)}
            return Command(goto=name, update=update)

        tools_node.__name__ = f"{name}_tools"
        return tools_node

    # ------------------------------------------------------------------ wiring
    g = StateGraph(SupportState)
    g.add_node("guard", guard, destinations=("entry", END))
    g.add_node("entry", entry, destinations=("triage", *AGENTS))
    g.add_node("triage", triage, destinations=(*AGENTS, END))
    for name in AGENTS:
        g.add_node(name, make_agent(name), destinations=(f"{name}_tools", END))
        g.add_node(f"{name}_tools", make_tools(name), destinations=AGENTS)
    g.add_edge(START, "guard")
    return g.compile(checkpointer=checkpointer if checkpointer is not None else InMemorySaver())


def _cited_sources(messages: Sequence[AnyMessage], reply: str) -> list[dict[str, str]]:
    """Help-center sources retrieved this turn, narrowed to those the reply cites."""
    retrieved: dict[str, dict[str, str]] = {}
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            break
        if isinstance(m, ToolMessage) and m.name == KB_TOOL and m.artifact:
            for src in m.artifact:
                retrieved.setdefault(src["source"], src)
    cited = [s for slug, s in retrieved.items() if f"[{slug}]" in reply]
    return cited or list(retrieved.values()) if retrieved else []
