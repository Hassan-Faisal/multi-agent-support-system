# 5. Human approval of large refunds is asynchronous, not a graph interrupt

**Status:** accepted

## Context

LangGraph's `interrupt()` can pause a run until a human resumes it. For refund approval that would block the customer's conversation until a staff member acted, possibly hours later.

## Decision

Over-limit refunds are created with status `pending_approval` and a high-priority ticket is opened in the same transaction. The agent tells the customer what happens next and the conversation continues. Staff decide in the console; the decision resolves the ticket, is audited, and shows up in the customer's account panel.

## Consequences

- Customers are never stuck waiting on a paused run; they can ask about something else immediately.
- The approval queue is ordinary data (filterable, countable, auditable) rather than a set of suspended graph threads.
- The customer learns the outcome from the account panel or email rather than inside the original chat. A notification hook is the natural extension.
- `interrupt()` remains the right tool for decisions that must happen *inside* a turn, such as asking the customer to confirm a destructive action.
