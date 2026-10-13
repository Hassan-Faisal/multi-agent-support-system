# Multi-Agent Customer Support System

A LangGraph-based support system where a **triage router** sends each customer to one of four
**specialist agents** that work with real tools, hand conversations to each other, and escalate
to humans. Ships with a FastAPI backend, a web chat UI with a live agent trace, mock data in
SQLite, and an offline test suite.

```
              ┌──────────┐
 customer ──▶ │  triage  │──(greeting)──▶ reply
              └────┬─────┘
                   ▼   (next turns go straight to the active agent)
   ┌─────────┐  ┌───────────┐  ┌────────┐  ┌────────────┐
   │ billing │◀▶│ technical │◀▶│ orders │◀▶│ escalation │──▶ ticket for a human
   └────┬────┘  └─────┬─────┘  └───┬────┘  └─────┬──────┘
     invoices      knowledge     orders,        support
     refunds         base       tracking,       tickets
                                 returns
```

| Agent | Handles | Tools |
|---|---|---|
| **Triage** | Classifies intent, answers small talk | structured output only |
| **Billing** | Invoices, charges, refunds | `list_invoices`, `request_refund` |
| **Technical** | Login, crashes, sync, 2FA, API | `search_knowledge_base` |
| **Orders** | Status, tracking, delays, returns | `list_orders`, `get_order_status`, `start_return` |
| **Escalation** | Hand-off to humans | `create_support_ticket` |

Every specialist also has `get_customer_profile` and `transfer_to_<other agent>` tools.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                     # add your ANTHROPIC_API_KEY
uvicorn app.server:app --reload
```

Open http://localhost:8000, pick a demo customer and try the suggested prompts.
The database is created and seeded automatically at `data/support.db`
(delete it to reset the demo).

Run tests (no API key needed — they use a scripted fake model):

```bash
pytest -q
```

## How it works

**Graph** (`app/graph.py`). Each turn enters at `entry`. If an agent is already handling the
conversation it goes straight there (sticky routing); otherwise `triage` picks one. Each specialist
is an LLM node plus a tools node that loop until the agent replies without tool calls. Calling a
`transfer_to_*` tool switches `active_agent` and jumps to that agent within the same turn, so the
customer gets one answer, not "please hold".

**Memory.** Conversation state is checkpointed per `customer_id:session_id` thread with
`MemorySaver`. For production, swap in `langgraph-checkpoint-postgres` or `-sqlite` in `build_graph`.

**Guardrails**
- *Policy in code, not prompts.* Refund limits/windows and return windows are enforced inside the
  tools; the model can't talk its way past them.
- *Tenant isolation.* Tools read the customer id from the run config, never from model arguments,
  so naming another customer's order or invoice id returns "not found".
- *Loop limits.* More than `SUPPORT_MAX_HANDOFFS` handoffs in a turn, or `SUPPORT_MAX_TOOL_STEPS`
  tool rounds by one agent, routes to escalation.
- *Tool errors* are returned to the model as messages instead of crashing the run.

**Trace.** Every route, handoff, tool call and guardrail trip is recorded in `state["events"]`;
the API returns the current turn's events and the UI shows them in the right-hand panel.

## API

| Method | Path | Notes |
|---|---|---|
| `POST` | `/api/chat` | `{session_id, customer_id, message}` → `{reply, agent, active_agent, events}` |
| `GET` | `/api/customers` | demo accounts |
| `GET` | `/api/customers/{id}` | profile, orders, invoices (with refund status), tickets |
| `GET` | `/api/tickets` | all escalation tickets (human queue) |
| `GET` | `/api/health` | model config / startup errors |

## Demo scenarios

| Customer | Try | What happens |
|---|---|---|
| Ayesha (C001) | "I was charged twice this month" | Billing finds INV-2002, auto-refunds $29 |
| Ayesha (C001) | "My app crashes when I open it" | Technical searches KB, walks through fixes |
| Marcus (C002) | "I want to return my desk lamp" | Orders refuses: delivered 50 days ago (30-day window) |
| Marcus (C002) | "I get a 403 from the API" | Technical explains Basic plan has no API access |
| Sofia (C003) | "Refund my last invoice" | $499 > $50 limit → pending → escalation ticket |
| Sofia (C003) | "My desk is late again, this is unacceptable" | Orders gives ETA; compensation → escalation |

## Taking it to production

1. **Data** — replace functions in `app/db.py` with calls to your order system, billing provider
   (e.g. Stripe) and helpdesk (Zendesk, Freshdesk…). Tool signatures stay the same.
2. **Auth** — `/api/chat` takes `customer_id` in the body for the demo. Read it from your session
   or JWT instead.
3. **Knowledge base** — swap the keyword search in `db.search_kb` for a vector store over your
   help-center articles.
4. **Persistence** — use a Postgres checkpointer so conversations survive restarts and scale
   across workers.
5. **Streaming** — switch the endpoint to `graph.astream(..., stream_mode="messages")` with
   Server-Sent Events for token-by-token replies.
6. **Observability** — set `LANGSMITH_API_KEY` and `LANGSMITH_TRACING=true` to trace every run.
7. **Evaluation** — extend `tests/` with real-model eval cases (routing accuracy, policy
   adherence) before changing prompts.

## Project layout

```
app/
  config.py      env settings, guardrail limits, policy numbers
  db.py          SQLite schema, seed data, query helpers (swap for real systems)
  tools.py       specialist tools + handoff tool factory
  prompts.py     triage + specialist system prompts
  graph.py       LangGraph state machine
  server.py      FastAPI app
  static/index.html   chat UI with agent trace
tests/           offline tests with a scripted fake model
```
