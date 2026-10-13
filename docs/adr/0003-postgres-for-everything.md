# 3. PostgreSQL for business data, vectors, full-text and agent checkpoints

**Status:** accepted

## Context

A typical RAG stack adds a dedicated vector database, and agent memory often goes to Redis. Each extra store adds operational cost, another consistency boundary and another thing to back up.

## Decision

Use one PostgreSQL instance: business tables, pgvector (HNSW, cosine) for embeddings, a generated `tsvector` with a GIN index for keyword search, and LangGraph's `AsyncPostgresSaver` for conversation checkpoints.

## Consequences

- One backup, one connection story, transactions across business data, and a single `docker compose up`.
- Hybrid search is two indexed queries on the same table; no sync job between stores.
- Conversations survive restarts (tested by restarting the app between turns).
- pgvector is comfortable into the low millions of chunks. A help center is far below that; a dedicated vector store becomes worth it only at much larger scale or with heavy filtering needs.
- The embedding dimension is fixed in the schema (1536). Changing embedding model families means a migration and a re-index; ingestion fingerprints include the model name so the re-index is automatic once the column changes.
