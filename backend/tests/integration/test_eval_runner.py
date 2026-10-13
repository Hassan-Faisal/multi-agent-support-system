"""The eval runner's plumbing, driven by scripted models (the real run needs API keys)."""

from pathlib import Path

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from support.api.container import build_container
from support.db.session import SessionFactory
from support.evals.checks import Case, evaluate
from support.evals.runner import run_case, run_retrieval
from support.rag.documents import load_directory
from support.rag.embeddings import HashingEmbedder
from support.rag.ingest import ingest
from support.settings import Settings
from tests.fakes import scripted, tool_call

pytestmark = pytest.mark.integration
EMB = HashingEmbedder(1536)
KB = load_directory(Path(__file__).resolve().parents[2] / "knowledge_base")


async def test_run_case_collects_routing_tools_and_side_effects(
    sessions: SessionFactory, settings: Settings
) -> None:
    await ingest(sessions, EMB, KB, settings)
    c = await build_container(
        settings,
        embedder=EMB,
        checkpointer=InMemorySaver(),
        triage_llm=scripted({"agent": "billing", "reason": "refund"}),
        llm=scripted(
            tool_call("request_refund", {"invoice_id": "INV-2005", "reason": "seats"}),
            "Your $499 refund is waiting for approval.",
        ),
    )
    case = Case.model_validate(
        {
            "id": "t",
            "customer": "C003",
            "turns": ["refund my invoice"],
            "expect": {
                "route": "billing",
                "tools": ["request_refund"],
                "refund": {"INV-2005": "pending_approval"},
                "min_tickets": 1,
                "reply_any": ["approv"],
            },
        }
    )
    try:
        rec = await run_case(c, case)
    finally:
        await c.aclose()
    assert rec.error is None
    assert all(ch.passed for ch in evaluate(case, rec)), evaluate(case, rec)


async def test_retrieval_benchmark_reports_recall_and_mrr(
    sessions: SessionFactory, settings: Settings
) -> None:
    await ingest(sessions, EMB, KB, settings)
    report = await run_retrieval(sessions, EMB)
    assert report["cases"] >= 20 and 0 < report["mrr"] <= report["recall"] <= 1
