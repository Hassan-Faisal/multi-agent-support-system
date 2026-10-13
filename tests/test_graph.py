"""End-to-end graph tests using a scripted model (no API key needed)."""
import json

import pytest

from app import config as settings
from app import db
from app.graph import build_graph
from tests.fake_llm import ScriptedChatModel, call


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DB_PATH", tmp_path / "test.db")
    db.init_db(reset=True)


def make(llm_script, triage_script):
    llm = ScriptedChatModel(responses=list(llm_script), calls=[])
    triage = ScriptedChatModel(responses=list(triage_script), calls=[])
    return build_graph(llm=llm, triage_llm=triage), llm, triage


def run(graph, text, thread="t1", customer="C001"):
    cfg = {"configurable": {"thread_id": thread, "customer_id": customer}}
    return graph.invoke({"messages": [("user", text)]}, cfg)


def test_small_talk_is_answered_by_triage():
    graph, _, _ = make([], [{"agent": "none", "reply": "Hello! How can I help?", "reason": "greeting"}])
    out = run(graph, "hi")
    assert out["messages"][-1].content == "Hello! How can I help?"
    assert out.get("active_agent") is None


def test_billing_refund_auto_approved_under_limit():
    graph, _, _ = make(
        [call("request_refund", {"invoice_id": "INV-2002", "reason": "duplicate charge"}),
         "Done! I've refunded $29.00 for the duplicate charge."],
        [{"agent": "billing", "reason": "duplicate charge"}],
    )
    out = run(graph, "I was charged twice this month")
    assert out["active_agent"] == "billing"
    tool_msg = out["messages"][-2]
    payload = json.loads(tool_msg.content)
    assert payload["ok"] and payload["refund"]["status"] == "approved"
    assert out["messages"][-1].name == "billing"


def test_refund_blocked_for_other_customers_invoice():
    graph, _, _ = make(
        [call("request_refund", {"invoice_id": "INV-2005", "reason": "x"}), "I couldn't find that invoice."],
        [{"agent": "billing", "reason": "refund"}],
    )
    out = run(graph, "refund INV-2005", customer="C001")  # INV-2005 belongs to C003
    assert "not found on this account" in out["messages"][-2].content


def test_large_refund_goes_pending_then_hands_off_to_escalation():
    graph, _, _ = make(
        [call("request_refund", {"invoice_id": "INV-2005", "reason": "unused"}),
         call("transfer_to_escalation", {"reason": "refund over limit"}, 1),
         call("create_support_ticket", {"category": "billing", "priority": "high",
                                        "summary": "Refund of $499 for INV-2005 needs approval"}, 2),
         "I've opened ticket TKT-XXXX; a human will approve within 4 hours."],
        [{"agent": "billing", "reason": "refund"}],
    )
    out = run(graph, "Refund my last enterprise invoice please", customer="C003")
    assert out["active_agent"] == "escalation"
    kinds = [e["type"] for e in out["events"]]
    assert kinds == ["route", "tool", "handoff", "tool"]
    assert len(db.list_tickets()) == 1
    assert out["messages"][-1].name == "escalation"


def test_sticky_agent_skips_triage_on_next_turn():
    graph, llm, triage = make(
        [call("get_order_status", {"order_id": "ORD-1002"}), "It's with FedEx, arriving in 2 days.",
         "You're welcome!"],
        [{"agent": "orders", "reason": "tracking"}],
    )
    run(graph, "where is ORD-1002?")
    out = run(graph, "thanks!")
    assert out["messages"][-1].content == "You're welcome!"
    assert triage.responses == []  # triage was called exactly once


def test_return_rejected_outside_window():
    graph, _, _ = make(
        [call("start_return", {"order_id": "ORD-1004", "reason": "broken"}), "Sorry, it's past 30 days."],
        [{"agent": "orders", "reason": "return"}],
    )
    out = run(graph, "return my lamp", customer="C002")
    assert "return window" in out["messages"][-2].content


def test_handoff_ping_pong_is_capped():
    # billing -> technical -> billing -> technical (4th handoff exceeds cap of 3) -> escalation
    script = [
        call("transfer_to_technical", {"reason": "a"}, 1),
        call("transfer_to_billing", {"reason": "b"}, 2),
        call("transfer_to_technical", {"reason": "c"}, 3),
        call("transfer_to_billing", {"reason": "d"}, 4),
        "Escalation here, I've got you.",
    ]
    graph, _, _ = make(script, [{"agent": "billing", "reason": "x"}])
    out = run(graph, "help")
    assert out["active_agent"] == "escalation"
    assert any(e["type"] == "guardrail" for e in out["events"])


def test_kb_search_finds_crash_article():
    hits = db.search_kb("my app keeps crashing on startup")
    assert hits[0]["id"] == "KB-02"
