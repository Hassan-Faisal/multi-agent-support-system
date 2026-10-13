from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from support.db.models import Base
from support.db.urls import to_asyncpg_url
from support.settings import get_settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def include_name(name: str | None, type_: str, parent_names: object) -> bool:
    """Only manage tables our models define. LangGraph's checkpointer creates and migrates
    its own tables (checkpoints, checkpoint_blobs, ...); without this filter, autogenerate
    would emit DROP TABLE for them and wipe every saved conversation."""
    if type_ == "table":
        return name in target_metadata.tables
    return True


def _url() -> str:
    # Allows `alembic -x url=...` (used by tests), else settings.
    url = context.get_x_argument(as_dictionary=True).get("url")
    return to_asyncpg_url(url) if url else get_settings().async_database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        include_name=include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection, target_metadata=target_metadata, compare_type=True, include_name=include_name
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_url())
    async with engine.connect() as conn:
        await conn.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
