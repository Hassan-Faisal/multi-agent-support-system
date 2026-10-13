"""FastAPI server: JSON API + the web chat UI.

Run:  uvicorn app.server:app --reload
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import config as settings
from app import db
from app.graph import build_graph

log = logging.getLogger("support")
STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    if getattr(app.state, "graph", None) is None:  # tests may inject their own graph
        try:
            app.state.graph = build_graph()
        except Exception as e:  # e.g. missing provider package
            log.error("Could not build graph: %s", e)
            app.state.graph = None
            app.state.graph_error = str(e)
    yield


app = FastAPI(title="Multi-Agent Customer Support", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class ChatIn(BaseModel):
    session_id: str = Field(min_length=1, max_length=100)
    customer_id: str
    message: str = Field(min_length=1, max_length=4000)


class ChatOut(BaseModel):
    reply: str
    agent: str
    active_agent: str | None
    events: list[dict]


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health():
    return {"ok": app.state.graph is not None, "model": settings.MODEL,
            "error": getattr(app.state, "graph_error", None)}


@app.get("/api/customers")
def customers():
    return db.list_customers()


@app.get("/api/customers/{customer_id}")
def customer_detail(customer_id: str):
    cust = db.get_customer(customer_id)
    if not cust:
        raise HTTPException(404, "Customer not found")
    invoices = [{**i, "refund": next((r["status"] for r in db.get_refunds_for_invoice(i["id"])), None)}
                for i in db.get_invoices(customer_id)]
    orders = [{**o, "return": next((r["status"] for r in db.get_returns_for_order(o["id"])), None)}
              for o in db.get_orders(customer_id)]
    return {**cust, "orders": orders, "invoices": invoices,
            "tickets": [t for t in db.list_tickets() if t["customer_id"] == customer_id]}


@app.get("/api/tickets")
def tickets():
    return db.list_tickets()


@app.post("/api/chat", response_model=ChatOut)
async def chat(body: ChatIn):
    graph = app.state.graph
    if graph is None:
        raise HTTPException(503, f"Agent graph unavailable: {getattr(app.state, 'graph_error', '')}")
    if not db.get_customer(body.customer_id):
        raise HTTPException(404, "Unknown customer")

    # In production the customer id comes from your auth session, never the request body.
    cfg = {"configurable": {"thread_id": f"{body.customer_id}:{body.session_id}",
                            "customer_id": body.customer_id}}
    before = await graph.aget_state(cfg)
    n_events = len(before.values.get("events", [])) if before.values else 0

    try:
        state = await graph.ainvoke({"messages": [("user", body.message)]}, cfg)
    except Exception as e:
        log.exception("Graph run failed")
        raise HTTPException(502, f"Agent error: {type(e).__name__}: {e}")

    last = state["messages"][-1]
    content = last.content
    if isinstance(content, list):  # some providers return content blocks
        content = "".join(b.get("text", "") for b in content if isinstance(b, dict))
    return ChatOut(reply=content or "(no reply)", agent=getattr(last, "name", None) or "assistant",
                   active_agent=state.get("active_agent"), events=state.get("events", [])[n_events:])
