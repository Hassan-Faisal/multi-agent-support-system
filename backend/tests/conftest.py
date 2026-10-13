"""Shared fixtures.

Integration tests run against a real PostgreSQL + pgvector database given by
TEST_DATABASE_URL (CI provides one as a service container). The schema is built by
running the actual Alembic migrations, so migrations are tested too. Each test starts
from freshly seeded data.
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from support.db.seed import reset, seed
from support.db.session import SessionFactory, create_session_factory, unit_of_work
from support.domain.policies import RefundPolicy, ReturnPolicy
from support.settings import Settings

BACKEND = Path(__file__).resolve().parents[1]
TEST_DB = os.getenv("TEST_DATABASE_URL")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if TEST_DB:
        return
    skip = pytest.mark.skip(reason="TEST_DATABASE_URL not set")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(
        env="test",
        database_url=TEST_DB or "postgresql+asyncpg://unused/unused",
        embedding_provider="hashing",
        log_json=False,
        rate_limit_per_minute=1000,
        _env_file=None,  # type: ignore[call-arg]
    )


@pytest.fixture(scope="session")
def refund_policy() -> RefundPolicy:
    return RefundPolicy(auto_approve_limit=Decimal("50.00"), window_days=30)


@pytest.fixture(scope="session")
def return_policy() -> ReturnPolicy:
    return ReturnPolicy(window_days=30)


@pytest.fixture(scope="session")
async def engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    assert TEST_DB, "integration fixture used without TEST_DATABASE_URL"
    eng = create_async_engine(TEST_DB)
    async with eng.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "alembic",
        "-x",
        f"url={TEST_DB}",
        "upgrade",
        "head",
        cwd=BACKEND,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    output, _ = await proc.communicate()
    assert proc.returncode == 0, output.decode()
    yield eng
    await eng.dispose()


@pytest.fixture
async def sessions(engine: AsyncEngine) -> SessionFactory:
    factory = create_session_factory(engine)
    async with unit_of_work(factory) as s:
        await reset(s)
        await s.execute(text("TRUNCATE kb_chunks, kb_documents RESTART IDENTITY CASCADE"))
        await seed(s)
    return factory
