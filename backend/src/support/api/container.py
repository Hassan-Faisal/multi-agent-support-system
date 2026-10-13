"""Composition root: builds and owns every long-lived dependency.

Constructed once at startup. Tests pass their own pieces (scripted models, in-memory
checkpointer, hashing embedder) instead of monkeypatching globals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.ext.asyncio import AsyncEngine

from support.agents.graph import GraphLimits, build_graph
from support.agents.tools import AgentDeps
from support.db.models import EMBEDDING_DIM
from support.db.session import SessionFactory, create_engine, create_session_factory
from support.domain.policies import RefundPolicy, ReturnPolicy
from support.rag.embeddings import Embedder, build_embedder
from support.rag.retriever import HybridRetriever
from support.security.ratelimit import RateLimiter, SlidingWindowLimiter
from support.settings import Settings


@dataclass
class Container:
    settings: Settings
    engine: AsyncEngine
    sessions: SessionFactory
    graph: CompiledStateGraph[Any, Any, Any, Any]
    limiter: RateLimiter
    refund_policy: RefundPolicy
    return_policy: ReturnPolicy
    _closers: list[Any] = field(default_factory=list)

    async def aclose(self) -> None:
        for close in reversed(self._closers):
            await close()
        await self.engine.dispose()


async def build_container(
    settings: Settings,
    *,
    llm: BaseChatModel | None = None,
    triage_llm: BaseChatModel | None = None,
    embedder: Embedder | None = None,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> Container:
    if settings.embedding_dim != EMBEDDING_DIM:
        raise RuntimeError(
            f"SUPPORT_EMBEDDING_DIM={settings.embedding_dim} but the index is {EMBEDDING_DIM}-d"
        )
    closers: list[Any] = []
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    embedder = embedder or build_embedder(settings)

    if llm is None or triage_llm is None:
        from support.agents.llm import build_chat_models

        default_llm, default_triage = build_chat_models(settings)
        llm, triage_llm = llm or default_llm, triage_llm or default_triage

    if checkpointer is None:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from psycopg.rows import dict_row
        from psycopg_pool import AsyncConnectionPool

        pool: AsyncConnectionPool[Any] = AsyncConnectionPool(
            settings.psycopg_url,
            min_size=1,  # default (4) would exceed small pools on free-tier databases
            max_size=max(1, settings.db_pool_size),
            # Serverless Postgres (e.g. Neon) suspends when idle; verify connections on checkout.
            check=AsyncConnectionPool.check_connection,
            open=False,
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        )
        await pool.open()
        closers.append(pool.close)
        saver = AsyncPostgresSaver(pool)
        await saver.setup()  # idempotent; creates checkpoint tables on first run
        checkpointer = saver

    refund_policy = RefundPolicy(settings.refund_auto_approve_limit, settings.refund_window_days)
    return_policy = ReturnPolicy(settings.return_window_days)
    deps = AgentDeps(
        sessions=sessions,
        retriever=HybridRetriever(
            sessions,
            embedder,
            candidates=settings.retrieval_candidates,
            min_score=settings.retrieval_min_score,
        ),
        refund_policy=refund_policy,
        return_policy=return_policy,
        retrieval_top_k=settings.retrieval_top_k,
    )
    graph = build_graph(
        deps=deps,
        llm=llm,
        triage_llm=triage_llm,
        checkpointer=checkpointer,
        limits=GraphLimits(
            settings.max_handoffs_per_turn,
            settings.max_tool_steps_per_agent,
            settings.max_context_messages,
            settings.injection_block_threshold,
            settings.triage_every_turn,
        ),
    )
    return Container(
        settings=settings,
        engine=engine,
        sessions=sessions,
        graph=graph,
        limiter=SlidingWindowLimiter(settings.rate_limit_per_minute),
        refund_policy=refund_policy,
        return_policy=return_policy,
        _closers=closers,
    )
