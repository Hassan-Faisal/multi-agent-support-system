# 2. Business policy is enforced in services, not prompts

**Status:** accepted

## Context

The tempting design puts rules in the system prompt ("only refund up to $50"). Models follow such rules most of the time, which isn't good enough for money, and prompt injection is aimed precisely at them.

## Decision

Rules are pure functions in `domain/policies.py`, called by transactional services that also scope every query by customer and lock rows they change. Tools are thin adapters that turn domain errors into structured results the model can explain. Prompts describe the policy only so the model communicates it well.

## Consequences

- The worst a manipulated model can do is ask for something that gets refused with a clear reason.
- The same rules apply to the staff console and the chat, with no duplication.
- Policies are unit-tested exhaustively without databases or models, including boundaries such as "$50.00 is auto-approved, $50.01 isn't".
- Changing a rule means changing code (and a test), not editing a prompt. That's intended.
