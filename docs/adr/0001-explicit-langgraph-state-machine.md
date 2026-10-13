# 1. Explicit LangGraph state machine instead of a prebuilt supervisor or swarm

**Status:** accepted

## Context

LangGraph ships higher-level helpers (`create_react_agent`, supervisor and swarm packages) that would give a working multi-agent system in a few lines. We need per-turn guardrails (PII, injection), limits on handoffs and tool rounds, a trace of every routing decision for the UI, and a router that screens every message for scope and topic changes.

## Decision

Build the graph by hand: `guard → entry → triage → specialist ⇄ tools`, with handoffs implemented as tools whose effect is applied by our own tools node returning `Command(goto=…)`.

## Consequences

- Every transition is visible in one file and covered by tests (cap trips, off-topic redirects, redaction before any model call).
- Trace events and metrics are emitted where decisions happen, not reconstructed afterwards.
- We own more code than with the prebuilt helpers, and must follow LangGraph API changes ourselves. The graph is about 300 lines, which we judged worth it for the control.
- Triage runs on every message. An earlier version skipped it for follow-ups to save a call, but off-topic chat then went straight to the active specialist, which happily chatted along. Screening each message costs one small-model call per turn and keeps every agent on task; when triage picks the agent that already has the conversation, it continues without a visible re-route.
