"""HTTP-level tests: the real app, real Postgres, scripted LLMs."""

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver

from support.api.container import Container, build_container
from support.db.session import SessionFactory
from support.main import create_app
from support.rag.documents import load_directory
from support.rag.embeddings import HashingEmbedder
from support.rag.ingest import ingest
from support.security.ratelimit import SlidingWindowLimiter
from support.settings import Settings
from tests.fakes import ScriptedChatModel, scripted, tool_call

pytestmark = pytest.mark.integration
KB = load_directory(Path(__file__).resolve().parents[2] / "knowledge_base")
EMB = HashingEmbedder(1536)


class Harness:
    def __init__(
        self,
        client: httpx.AsyncClient,
        container: Container,
        llm: ScriptedChatModel,
        triage: ScriptedChatModel,
    ) -> None:
        self.client, self.container, self.llm, self.triage = client, container, llm, triage

    async def login(self, email: str) -> dict[str, str]:
        r = await self.client.post("/api/v1/auth/login", json={"email": email, "password": "demo1234"})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
async def h(sessions: SessionFactory, settings: Settings) -> AsyncIterator[Harness]:
    await ingest(sessions, EMB, KB, settings)
    llm, triage = scripted(), scripted()
    container = await build_container(
        settings, llm=llm, triage_llm=triage, embedder=EMB, checkpointer=InMemorySaver()
    )
    app = create_app(settings, container)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield Harness(client, container, llm, triage)
    await app.state.chat_runner.drain()
    await container.aclose()


async def new_conversation(h: Harness, auth: dict[str, str]) -> str:
    r = await h.client.post("/api/v1/conversations", headers=auth)
    assert r.status_code == 201
    return str(r.json()["id"])


def parse_sse(body: str) -> list[tuple[str, dict[str, Any]]]:
    events = []
    for block in body.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        events.append((fields["event"], json.loads(fields["data"])))
    return events


# ------------------------------------------------------------------ auth
async def test_login_and_me(h: Harness) -> None:
    auth = await h.login("ayesha@example.com")
    me = (await h.client.get("/api/v1/auth/me", headers=auth)).json()
    assert me["role"] == "customer" and me["customer_id"] == "C001"
    bad = await h.client.post("/api/v1/auth/login", json={"email": "ayesha@example.com", "password": "nope"})
    assert bad.status_code == 401
    unknown = await h.client.post("/api/v1/auth/login", json={"email": "who@example.com", "password": "nope"})
    assert unknown.status_code == 401 and unknown.json() == bad.json()


async def test_authorization_boundaries(h: Harness) -> None:
    assert (await h.client.get("/api/v1/me/account")).status_code == 401
    customer = await h.login("ayesha@example.com")
    assert (await h.client.get("/api/v1/admin/tickets", headers=customer)).status_code == 403
    agent = await h.login("agent@nimbus.example")
    assert (await h.client.post("/api/v1/conversations", headers=agent)).status_code == 403

    conv = await new_conversation(h, customer)
    other = await h.login("marcus@example.com")
    r = await h.client.get(f"/api/v1/conversations/{conv}/messages", headers=other)
    assert r.status_code == 404 and r.headers["content-type"] == "application/problem+json"
    assert (await h.client.get(f"/api/v1/conversations/{conv}/messages", headers=agent)).status_code == 200


# ------------------------------------------------------------------ chat
async def test_json_turn_and_transcript(h: Harness) -> None:
    h.triage.responses += [{"agent": "orders", "reason": "tracking"}]
    h.llm.responses += [
        tool_call("get_order_status", {"order_id": "ORD-1002"}),
        "It's with FedEx (FX998877).",
    ]
    auth = await h.login("ayesha@example.com")
    conv = await new_conversation(h, auth)

    r = await h.client.post(
        f"/api/v1/conversations/{conv}/messages", headers=auth, json={"content": "Where is ORD-1002?"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["message"]["agent"] == "orders" and "FedEx" in body["message"]["content"]
    assert [e["type"] for e in body["events"]] == ["route", "tool"]

    transcript = (await h.client.get(f"/api/v1/conversations/{conv}/messages", headers=auth)).json()
    assert [(m["role"], m["agent"]) for m in transcript] == [("customer", None), ("assistant", "orders")]
    convs = (await h.client.get("/api/v1/conversations", headers=auth)).json()
    assert convs[0]["title"] == "Where is ORD-1002?" and convs[0]["active_agent"] == "orders"


async def test_sse_turn_streams_trace_then_message(h: Harness) -> None:
    h.triage.responses += [{"agent": "technical", "reason": "crash"}]
    h.llm.responses += [
        tool_call("search_help_center", {"query": "app crash"}),
        "Update the app first [app-crashes].",
    ]
    auth = await h.login("ayesha@example.com")
    conv = await new_conversation(h, auth)
    r = await h.client.post(
        f"/api/v1/conversations/{conv}/messages",
        json={"content": "app keeps crashing"},
        headers={**auth, "Accept": "text/event-stream"},
    )
    assert r.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(r.text)
    types = [t for t, _ in events]
    assert types[-2:] == ["message", "done"] and "trace" in types
    message = dict(events)["message"]["message"]
    assert message["sources"][0]["source"] == "app-crashes"


async def test_second_message_while_replying_gets_409(h: Harness) -> None:
    h.triage.delay_s = 0.3
    h.triage.responses += [{"agent": "none", "reason": "greeting", "small_talk": "greeting"}]
    auth = await h.login("ayesha@example.com")
    conv = await new_conversation(h, auth)
    url = f"/api/v1/conversations/{conv}/messages"
    first, second = await asyncio.gather(
        h.client.post(url, headers=auth, json={"content": "hello"}),
        h.client.post(url, headers=auth, json={"content": "hello again"}),
    )
    assert sorted([first.status_code, second.status_code]) == [200, 409]


async def test_chat_is_rate_limited(h: Harness) -> None:
    h.container.limiter = SlidingWindowLimiter(limit=1)
    h.triage.responses += [{"agent": "none", "reason": "hi", "small_talk": "greeting"}]
    auth = await h.login("ayesha@example.com")
    conv = await new_conversation(h, auth)
    url = f"/api/v1/conversations/{conv}/messages"
    assert (await h.client.post(url, headers=auth, json={"content": "hi"})).status_code == 200
    limited = await h.client.post(url, headers=auth, json={"content": "hi"})
    assert limited.status_code == 429 and int(limited.headers["retry-after"]) >= 1


async def test_delete_conversation_removes_history_but_keeps_tickets(h: Harness) -> None:
    h.triage.responses += [{"agent": "escalation", "reason": "wants a human"}]
    h.llm.responses += [
        tool_call("create_support_ticket", {"category": "other", "priority": "normal", "summary": "Call me"}),
        "Ticket opened.",
    ]
    auth = await h.login("ayesha@example.com")
    keep, conv = await new_conversation(h, auth), await new_conversation(h, auth)
    await h.client.post(f"/api/v1/conversations/{conv}/messages", headers=auth, json={"content": "human pls"})

    other = await h.login("marcus@example.com")
    assert (await h.client.delete(f"/api/v1/conversations/{conv}", headers=other)).status_code == 404

    r = await h.client.delete(f"/api/v1/conversations/{conv}", headers=auth)
    assert r.status_code == 204
    ids = [c["id"] for c in (await h.client.get("/api/v1/conversations", headers=auth)).json()]
    assert ids == [keep]
    assert (await h.client.get(f"/api/v1/conversations/{conv}/messages", headers=auth)).status_code == 404
    snap = await h.container.graph.aget_state({"configurable": {"thread_id": conv}})
    assert not snap.values  # checkpointed messages are gone too
    assert (await h.client.delete(f"/api/v1/conversations/{conv}", headers=auth)).status_code == 404

    staff = await h.login("agent@nimbus.example")
    tickets = (await h.client.get("/api/v1/admin/tickets", headers=staff)).json()
    assert any(t["summary"] == "Call me" for t in tickets)  # staff work isn't lost
    actions = [e["action"] for e in (await h.client.get("/api/v1/admin/audit", headers=staff)).json()]
    assert actions[0] == "conversation.deleted"


async def test_cannot_delete_while_a_reply_is_being_written(h: Harness) -> None:
    h.triage.delay_s = 0.3
    h.triage.responses += [{"agent": "none", "reason": "greeting", "small_talk": "greeting"}]
    auth = await h.login("ayesha@example.com")
    conv = await new_conversation(h, auth)

    async def delete_soon() -> httpx.Response:
        await asyncio.sleep(0.05)
        return await h.client.delete(f"/api/v1/conversations/{conv}", headers=auth)

    sent, deleted = await asyncio.gather(
        h.client.post(f"/api/v1/conversations/{conv}/messages", headers=auth, json={"content": "hi"}),
        delete_soon(),
    )
    assert sent.status_code == 200 and deleted.status_code == 409


# ------------------------------------------------------------------ human-in-the-loop
async def test_refund_approval_round_trip(h: Harness) -> None:
    h.triage.responses += [{"agent": "billing", "reason": "refund"}]
    h.llm.responses += [
        tool_call("request_refund", {"invoice_id": "INV-2005", "reason": "unused"}),
        "Your refund is pending approval.",
    ]
    sofia = await h.login("sofia@example.com")
    conv = await new_conversation(h, sofia)
    await h.client.post(
        f"/api/v1/conversations/{conv}/messages", headers=sofia, json={"content": "refund my last invoice"}
    )

    agent = await h.login("agent@nimbus.example")
    stats = (await h.client.get("/api/v1/admin/stats", headers=agent)).json()
    assert stats["pending_refunds"] == 1 and stats["open_tickets"] == 1
    (pending,) = (await h.client.get("/api/v1/admin/refunds?status=pending_approval", headers=agent)).json()
    url = f"/api/v1/admin/refunds/{pending['id']}/decision"
    r = await h.client.post(url, headers=agent, json={"approve": True, "note": "loyal customer"})
    assert r.json()["status"] == "approved"
    again = await h.client.post(url, headers=agent, json={"approve": False})
    assert again.status_code == 409 and again.json()["type"].endswith("/conflict")

    account = (await h.client.get("/api/v1/me/account", headers=sofia)).json()
    refund = next(i for i in account["invoices"] if i["id"] == "INV-2005")["refunds"][0]
    assert refund["status"] == "approved" and account["tickets"][0]["status"] == "resolved"
    actions = [e["action"] for e in (await h.client.get("/api/v1/admin/audit", headers=agent)).json()]
    assert actions[:3] == ["refund.approved", "ticket.status_changed", "refund.requested"]


# ------------------------------------------------------------------ persistence
async def test_conversations_survive_restart_with_postgres_checkpointer(
    sessions: SessionFactory, settings: Settings
) -> None:
    """Uses the production AsyncPostgresSaver: a second container (a restarted process)
    sees the history and keeps the sticky agent."""
    await ingest(sessions, EMB, KB, settings)
    triage = scripted({"agent": "orders", "reason": "tracking"})
    first = await build_container(settings, llm=scripted("It's on the way."), triage_llm=triage, embedder=EMB)
    app = create_app(settings, first)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        h = Harness(client, first, scripted(), triage)
        auth = await h.login("ayesha@example.com")
        conv = await new_conversation(h, auth)
        r = await client.post(
            f"/api/v1/conversations/{conv}/messages", headers=auth, json={"content": "my order?"}
        )
        assert r.status_code == 200
    await first.aclose()

    second = await build_container(
        settings,
        llm=scripted("Anything else?"),
        triage_llm=scripted({"agent": "orders", "reason": "same order"}),
        embedder=EMB,
    )
    app2 = create_app(settings, second)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app2), base_url="http://t") as client:
        transcript = (await client.get(f"/api/v1/conversations/{conv}/messages", headers=auth)).json()
        assert [m["content"] for m in transcript] == ["my order?", "It's on the way."]
        r = await client.post(
            f"/api/v1/conversations/{conv}/messages", headers=auth, json={"content": "thanks"}
        )
        assert r.json()["message"]["agent"] == "orders"  # active agent restored from the checkpoint
    await second.aclose()


# ------------------------------------------------------------------ ops
async def test_health_readiness_and_metrics(h: Harness) -> None:
    assert (await h.client.get("/healthz")).json() == {"status": "ok"}
    assert (await h.client.get("/readyz")).json() == {"status": "ready"}
    metrics = (await h.client.get("/metrics")).text
    assert "support_http_requests_total" in metrics
    r = await h.client.get("/healthz", headers={"X-Request-ID": "abc123"})
    assert r.headers["x-request-id"] == "abc123"
