"""API tests: the FastAPI app with an injected scripted graph."""
import pytest
from fastapi.testclient import TestClient

from app import config as settings
from app import db
from app.graph import build_graph
from app.server import app
from tests.fake_llm import ScriptedChatModel, call


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DB_PATH", tmp_path / "test.db")
    db.init_db(reset=True)
    llm = ScriptedChatModel(responses=[
        call("get_order_status", {"order_id": "ORD-1002"}),
        "Your headphones are with FedEx (FX998877), arriving in about 2 days.",
        call("transfer_to_billing", {"reason": "duplicate charge"}, 1),
        call("request_refund", {"invoice_id": "INV-2002", "reason": "duplicate"}, 2),
        "Refunded $29.00, back on your card in 5-7 business days.",
    ], calls=[])
    triage = ScriptedChatModel(responses=[{"agent": "orders", "reason": "tracking"}], calls=[])
    app.state.graph = build_graph(llm=llm, triage_llm=triage)
    with TestClient(app) as c:
        yield c
    app.state.graph = None


def chat(client, msg, session="s1", customer="C001"):
    r = client.post("/api/chat", json={"session_id": session, "customer_id": customer, "message": msg})
    assert r.status_code == 200, r.text
    return r.json()


def test_index_and_customers(client):
    assert "Agent trace" in client.get("/").text
    assert [c["id"] for c in client.get("/api/customers").json()] == ["C001", "C002", "C003"]


def test_conversation_with_handoff(client):
    r1 = chat(client, "Where is ORD-1002?")
    assert r1["agent"] == "orders" and r1["active_agent"] == "orders"
    assert [e["type"] for e in r1["events"]] == ["route", "tool"]

    r2 = chat(client, "Also I was charged twice")  # sticky -> orders, which hands off
    assert r2["agent"] == "billing" and r2["active_agent"] == "billing"
    assert [e["type"] for e in r2["events"]] == ["handoff", "tool"]  # only this turn's events

    detail = client.get("/api/customers/C001").json()
    assert detail["id"] == "C001" and len(detail["orders"]) == 2


def test_unknown_customer_rejected(client):
    r = client.post("/api/chat", json={"session_id": "s", "customer_id": "NOPE", "message": "hi"})
    assert r.status_code == 404
