from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from sqlalchemy import func, select

from support.db.models import KbChunk
from support.db.session import SessionFactory
from support.rag.documents import load_directory
from support.rag.embeddings import HashingEmbedder
from support.rag.ingest import ingest
from support.rag.retriever import HybridRetriever
from support.settings import Settings

pytestmark = pytest.mark.integration
BACKEND = Path(__file__).resolve().parents[2]
KB = load_directory(BACKEND / "knowledge_base")
EMB = HashingEmbedder(1536)


async def _chunks(sessions: SessionFactory) -> int:
    async with sessions() as s:
        return int(await s.scalar(select(func.count()).select_from(KbChunk)) or 0)


async def test_ingestion_is_idempotent_and_tracks_changes(
    sessions: SessionFactory, settings: Settings
) -> None:
    first = await ingest(sessions, EMB, KB, settings)
    assert len(first.added) == len(KB) and first.chunks_written == await _chunks(sessions)

    second = await ingest(sessions, EMB, KB, settings)
    assert second.added == second.updated == [] and len(second.unchanged) == len(KB)

    edited = [replace(KB[0], body=KB[0].body + "\n\n## New section\n\nFresh content."), *KB[1:-1]]
    third = await ingest(sessions, EMB, edited, settings)
    assert third.updated == [KB[0].slug] and third.removed == [KB[-1].slug]


async def test_hybrid_retrieval_quality_on_labelled_queries(
    sessions: SessionFactory, settings: Settings
) -> None:
    """Guards against retrieval regressions. With the lexical-only hashing embedder this
    is a floor; the real-embedding run lives in the eval suite."""
    await ingest(sessions, EMB, KB, settings)
    retriever = HybridRetriever(sessions, EMB)
    cases = yaml.safe_load((BACKEND / "evals" / "retrieval_cases.yaml").read_text())
    hits, misses = 0, []
    for case in cases:
        got = [c.slug for c in await retriever.search(case["query"], top_k=3)]
        if set(got) & set(case["expected"]):
            hits += 1
        else:
            misses.append((case["query"], got))
    recall = hits / len(cases)
    assert recall >= 0.85, f"recall@3={recall:.2f}, misses={misses}"


async def test_exact_tokens_are_found_by_keyword_search(sessions: SessionFactory, settings: Settings) -> None:
    await ingest(sessions, EMB, KB, settings)
    results = await HybridRetriever(sessions, EMB).search("403", top_k=2)
    assert results[0].slug == "api-errors" and "keyword" in results[0].matched_by


async def test_results_are_diversified_across_documents(sessions: SessionFactory, settings: Settings) -> None:
    await ingest(sessions, EMB, KB, settings)
    results = await HybridRetriever(sessions, EMB, max_chunks_per_doc=1).search(
        "refund invoice card", top_k=4
    )
    slugs = [r.slug for r in results]
    assert len(slugs) == len(set(slugs))
