# 1. Explicit LangGraph state machine instead of a prebuilt supervisor or swarm

**Status:** accepted

## Context

LangGraph ships higher-level helpers (`create_react_agent`, supervisor and swarm packages) that would give a working multi-agent system in a few lines. We need per-turn guardrails (PII, injection), limits on handoffs and tool rounds, a trace of every routing decision for the UI, and sticky routing so follow-ups skip the router.

## Decision

Build the graph by hand: `guard → entry → triage → specialist ⇄ tools`, with handoffs implemented as tools whose effect is applied by our own tools node returning `Command(goto=…)`.

## Consequences

- Every transition is visible in one file and covered by tests (cap trips, sticky routing, redaction before any model call).
- Trace events and metrics are emitted where decisions happen, not reconstructed afterwards.
- We own more code than with the prebuilt helpers, and must follow LangGraph API changes ourselves. The graph is about 300 lines, which we judged worth it for the control.
- Sticky routing saves a triage call on most follow-up messages; specialists hand off when the topic changes.
