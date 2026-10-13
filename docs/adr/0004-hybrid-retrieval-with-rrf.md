# 4. Hybrid retrieval fused with Reciprocal Rank Fusion

**Status:** accepted

## Context

Support questions mix paraphrase ("the app dies when I open it") with exact tokens ("403", "2FA", order ids). Embeddings handle the first and blur the second; keyword search is the opposite.

## Decision

Run semantic (pgvector) and keyword (Postgres full-text, OR'd terms) retrieval in parallel, take the top 20 of each, and fuse by Reciprocal Rank Fusion (k = 60). Cap results at two chunks per document so one long article can't crowd out others. Chunks carry their heading path, which is prepended before embedding.

## Alternatives considered

- **Weighted score blending:** cosine similarity and `ts_rank_cd` live on different, query-dependent scales; weights would need constant tuning. RRF uses ranks only.
- **Keyword AND (websearch_to_tsquery):** natural-language questions rarely contain every term of the right chunk; OR-ing informative terms and letting rank decide works better.
- **Cross-encoder reranking:** a clear next step for quality, left out to keep the default stack free of an extra model call. It slots in after fusion.

## Consequences

- The retrieval benchmark (22 labelled queries) reaches recall@3 91% even with the offline lexical embedder; the remaining misses are paraphrases the semantic half targets.
- A regression test fails the build if recall@3 drops below 85%.
