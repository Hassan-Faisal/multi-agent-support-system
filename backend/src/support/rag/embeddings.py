"""Embedding providers behind a small protocol.

`OpenAIEmbedder` is the production default. `HashingEmbedder` is a deterministic,
offline feature-hashing embedder used in tests and keyless local runs: it captures
lexical overlap only (no semantics), so the hybrid retriever still works, just with
weaker recall on paraphrases. Never use it in production.
"""

from __future__ import annotations

import hashlib
import math
import re
from itertools import pairwise
from typing import Protocol

from support.settings import Settings


class Embedder(Protocol):
    model_name: str
    dim: int

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


class OpenAIEmbedder:
    def __init__(
        self, api_key: str, model: str, dim: int, batch_size: int = 96, timeout_s: float = 30.0
    ) -> None:
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key, timeout=timeout_s, max_retries=3)
        self.model_name, self.dim, self._batch = model, dim, batch_size

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self._batch):
            resp = await self._client.embeddings.create(
                model=self.model_name, input=texts[i : i + self._batch], dimensions=self.dim
            )
            out.extend(d.embedding for d in sorted(resp.data, key=lambda d: d.index))
        return out

    async def embed_query(self, text: str) -> list[float]:
        return (await self.embed_documents([text]))[0]


_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "can",
        "do",
        "for",
        "from",
        "has",
        "have",
        "how",
        "i",
        "if",
        "in",
        "is",
        "it",
        "its",
        "my",
        "of",
        "on",
        "or",
        "so",
        "that",
        "the",
        "this",
        "to",
        "was",
        "we",
        "what",
        "when",
        "where",
        "which",
        "why",
        "will",
        "with",
        "you",
        "your",
    ]
)


class HashingEmbedder:
    def __init__(self, dim: int) -> None:
        self.dim = dim
        self.model_name = f"hashing-{dim}"

    @staticmethod
    def _norm(token: str) -> str:
        return token[:-1] if len(token) > 4 and token.endswith("s") else token

    def _vector(self, text: str) -> list[float]:
        words = [self._norm(t) for t in _TOKEN.findall(text.lower()) if t not in _STOP]
        features = words + [f"{a}_{b}" for a, b in pairwise(words)]
        vec = [0.0] * self.dim
        for f in features:
            h = int.from_bytes(hashlib.blake2b(f.encode(), digest_size=8).digest(), "big")
            vec[h % self.dim] += 1.0 if (h >> 63) & 1 else -1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


def build_embedder(settings: Settings) -> Embedder:
    if settings.embedding_provider == "hashing":
        return HashingEmbedder(settings.embedding_dim)
    if settings.openai_api_key is None:
        raise RuntimeError(
            "OPENAI_API_KEY is required for embedding_provider=openai "
            "(set SUPPORT_EMBEDDING_PROVIDER=hashing for an offline, lexical-only fallback)"
        )
    return OpenAIEmbedder(
        settings.openai_api_key.get_secret_value(), settings.embedding_model, settings.embedding_dim
    )
