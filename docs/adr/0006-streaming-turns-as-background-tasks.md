# 6. Each turn runs as a background task streaming over SSE

**Status:** accepted

## Context

If the graph runs inside the HTTP response generator, a closed tab or flaky mobile connection cancels the run midway: tools may have acted (a refund was created) but no reply is checkpointed. WebSockets would also work, but add connection management the rest of the API doesn't need.

## Decision

`ChatRunner.start_turn` launches the graph in an `asyncio` task that writes events to a queue; the SSE response reads from the queue. If the client disconnects, the task still finishes and checkpoints, and the reply appears when the customer reloads. The browser reads SSE through `fetch` (so it can POST and send an `Authorization` header), with an incremental parser that handles split chunks and multi-byte characters.

Concurrent turns on one conversation are rejected with 409 before the stream starts, because interleaved runs would corrupt the checkpoint sequence.

## Consequences

- No lost or half-written turns from client disconnects; shutdown drains in-flight turns.
- The busy set is in process memory; with several replicas it moves to a shared lock (see Known limitations in the README).
- The same runner serves a non-streaming JSON mode for integrations and tests.
