"""Idempotent knowledge-base ingestion.

Each document is fingerprinted over its content plus the chunker version, chunk
sizes and embedding model. Unchanged documents are skipped (no embedding cost),
changed ones are re-chunked and re-embedded, and documents deleted from disk are
removed from the index. Safe to run on every deploy.

    python -m support.rag.ingest
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from sqlalchemy import delete, select

from support.db.models import EMBEDDING_DIM, KbChunk, KbDocument
from support.db.session import SessionFactory, create_engine, create_session_factory, unit_of_work
from support.observability.logs import configure_logging, get_logger
from support.rag.chunking import CHUNKER_VERSION, chunk_markdown
from support.rag.documents import SourceDocument, load_directory
from support.rag.embeddings import Embedder, build_embedder
from support.settings import Settings, get_settings

log = get_logger(__name__)


@dataclass
class IngestReport:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    chunks_written: int = 0


async def ingest(
    sessions: SessionFactory, embedder: Embedder, docs: list[SourceDocument], settings: Settings
) -> IngestReport:
    if embedder.dim != EMBEDDING_DIM:
        raise ValueError(f"embedder dim {embedder.dim} != index dim {EMBEDDING_DIM}")
    report = IngestReport()
    setup = (
        CHUNKER_VERSION,
        str(settings.chunk_max_chars),
        str(settings.chunk_overlap_chars),
        embedder.model_name,
    )

    async with unit_of_work(sessions) as s:
        existing = {d.slug: d for d in (await s.scalars(select(KbDocument))).all()}

    for doc in docs:
        fp = doc.fingerprint(*setup)
        current = existing.get(doc.slug)
        if current and current.content_hash == fp:
            report.unchanged.append(doc.slug)
            continue

        chunks = chunk_markdown(
            doc.title,
            doc.body,
            max_chars=settings.chunk_max_chars,
            overlap_chars=settings.chunk_overlap_chars,
        )
        vectors = await embedder.embed_documents([c.embedding_text for c in chunks])  # outside the txn

        async with unit_of_work(sessions) as s:
            if current:
                await s.execute(delete(KbChunk).where(KbChunk.document_id == current.id))
                row = await s.get(KbDocument, current.id)
                assert row is not None
                row.title, row.url, row.category = doc.title, doc.url, doc.category
                row.content_hash, row.embedding_model = fp, embedder.model_name
                report.updated.append(doc.slug)
            else:
                row = KbDocument(
                    slug=doc.slug,
                    title=doc.title,
                    url=doc.url,
                    category=doc.category,
                    content_hash=fp,
                    embedding_model=embedder.model_name,
                )
                s.add(row)
                report.added.append(doc.slug)
            await s.flush()
            s.add_all(
                KbChunk(
                    document_id=row.id, chunk_index=c.index, heading=c.heading, content=c.content, embedding=v
                )
                for c, v in zip(chunks, vectors, strict=True)
            )
        report.chunks_written += len(chunks)

    stale = set(existing) - {d.slug for d in docs}
    if stale:
        async with unit_of_work(sessions) as s:
            await s.execute(delete(KbDocument).where(KbDocument.slug.in_(stale)))
        report.removed = sorted(stale)
    return report


async def _main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    engine = create_engine(settings)
    try:
        report = await ingest(
            create_session_factory(engine),
            build_embedder(settings),
            load_directory(settings.kb_dir),
            settings,
        )
        log.info(
            "kb.ingested",
            added=report.added,
            updated=report.updated,
            removed=report.removed,
            unchanged=len(report.unchanged),
            chunks=report.chunks_written,
        )
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
