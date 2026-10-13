# Security model

The design assumption: **the language model can be manipulated.** Security therefore can't depend on the model following instructions. It depends on what the model is *able* to do, which is limited to calling tools that enforce authorization and policy in code.

## Threats and controls

| Threat | Control | Where |
|---|---|---|
| Customer asks the agent to act on someone else's account | Tools take the customer id from the run config (set from the JWT), never from arguments. Every query is scoped by customer; "not yours" and "doesn't exist" return the same error. | `agents/tools.py`, `services/*` |
| Prompt injection talks the agent past policy | Refund limits, windows and one-per-invoice are enforced by `domain/policies.py` inside the service, under a row lock. Over-limit refunds can only become *pending*. | `domain/policies.py`, `services/billing.py` |
| Direct injection ("ignore previous instructions…") | Heuristic scoring in the guard node; blatant attempts get a fixed refusal with no model call, borderline ones are flagged in the trace. | `security/injection.py` |
| Indirect injection via help-center content | Retrieved text is HTML-escaped and fenced in `<search_results>` with an explicit "data, not instructions" note; prompts repeat it. Content is first-party, but treated as untrusted anyway. | `rag/retriever.py` |
| Payment data or SSNs sent to the model or logs | Luhn-validated card numbers, SSNs and IBANs are redacted in the guard node before triage, and again by a log processor. The original text is replaced in the checkpoint. | `security/pii.py`, `observability/logs.py` |
| Double refunds through concurrent requests | `SELECT … FOR UPDATE` on the invoice; tested with three concurrent attempts. | `services/billing.py` |
| Runaway agent loops (cost, latency) | Handoff cap and tool-step cap per turn, turn timeout, per-user rate limit, one turn per conversation at a time. | `agents/graph.py`, `api/chat.py` |
| Account enumeration on login | Same error and equivalent hashing work for unknown users and wrong passwords. | `api/routes/auth.py` |
| Privilege escalation to staff endpoints | Role checked on every staff route; customers get 403, staff can't post as customers. | `api/deps.py` |
| Untraceable actions | Every state change, by an agent or a person, is written to `audit_log` in the same transaction. | `services/audit.py` |
| XSS in the web app | React escaping, Markdown rendered without raw HTML, strict CSP from nginx, no inline scripts. | `frontend/nginx.conf` |

## Residual risks

- **Paraphrased injection** that slips past the heuristics can still make the model *say* something wrong. It can't *do* anything the customer couldn't do through the UI. An LLM-based classifier would reduce the first part.
- **Process-local limits:** the rate limiter and busy-conversation guard live in memory, so multiple replicas each enforce their own. Move them to Redis or Postgres before scaling out.
- **Token storage:** JWTs sit in `sessionStorage`. Production should use HttpOnly, SameSite cookies with CSRF protection.
- **Demo accounts** are served on the login page when `SUPPORT_ENABLE_DEMO_ACCOUNTS=true` and never when `SUPPORT_ENV=prod`.
- **Provider data retention:** the OpenAI Responses API stores responses by default (for multi-turn state). Card numbers and SSNs are already redacted before any request, but for stricter requirements pass `store=False` in `agents/llm.py` or use a zero-data-retention agreement.
- **Secrets** come from the environment. Use a secrets manager in production and rotate `SUPPORT_JWT_SECRET` (rotation invalidates sessions).
