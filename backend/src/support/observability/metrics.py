"""Prometheus metrics. Exposed at /metrics.

Label sets are kept small and bounded (agent names, tool names, outcomes) to avoid
cardinality blow-ups; never label with user ids or free text.
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram

HTTP_REQUESTS = Counter("support_http_requests_total", "HTTP requests", ["method", "route", "status"])
HTTP_LATENCY = Histogram("support_http_request_seconds", "HTTP latency", ["method", "route"])

TURNS = Counter("support_turns_total", "Customer turns processed", ["outcome"])
TURN_LATENCY = Histogram(
    "support_turn_seconds",
    "End-to-end latency of one customer turn",
    buckets=(0.5, 1, 2, 4, 8, 15, 30, 60, 120),
)
ROUTES = Counter("support_triage_routes_total", "Triage routing decisions", ["agent"])
HANDOFFS = Counter("support_handoffs_total", "Agent-to-agent handoffs", ["source", "target"])
TOOL_CALLS = Counter("support_tool_calls_total", "Tool invocations", ["agent", "tool", "outcome"])
GUARDRAILS = Counter("support_guardrail_events_total", "Guardrail trips", ["kind"])
LLM_TOKENS = Counter("support_llm_tokens_total", "LLM tokens", ["agent", "direction"])
RETRIEVALS = Histogram("support_retrieval_seconds", "Knowledge-base retrieval latency")
