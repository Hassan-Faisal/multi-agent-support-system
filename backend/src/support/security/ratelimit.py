"""Per-key sliding-window rate limiter.

In-process implementation behind a small protocol. With more than one API replica,
swap in a Redis implementation (sorted set per key) with the same interface.
"""
from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from typing import Protocol


class RateLimiter(Protocol):
    async def hit(self, key: str) -> tuple[bool, float]:
        """Record a hit. Returns (allowed, retry_after_seconds)."""
        ...


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_s: float = 60.0) -> None:
        self.limit, self.window = limit, window_s
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def hit(self, key: str) -> tuple[bool, float]:
        now = time.monotonic()
        async with self._lock:
            q = self._hits[key]
            while q and now - q[0] >= self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False, round(self.window - (now - q[0]), 1)
            q.append(now)
            return True, 0.0
