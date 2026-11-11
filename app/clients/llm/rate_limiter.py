"""Client-side request pacing for LLM providers.

Free tiers (e.g. Gemini) allow only a few requests per minute. A large plan writes many
Confluence pages back to back, which used to exhaust the quota and fail steps with HTTP 429.
Pacing calls up front is far cheaper than recovering from 429s.
"""

import asyncio
import time
from collections import deque


class RateLimiter:
    """Sliding-window limiter: at most ``per_minute`` acquisitions in any 60 seconds."""

    def __init__(self, per_minute: int, window_seconds: float = 60.0) -> None:
        self._limit = per_minute
        self._window = window_seconds
        self._stamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return self._limit > 0

    async def acquire(self) -> None:
        if not self.enabled:
            return
        async with self._lock:
            while True:
                now = time.monotonic()
                while self._stamps and now - self._stamps[0] >= self._window:
                    self._stamps.popleft()
                if len(self._stamps) < self._limit:
                    self._stamps.append(now)
                    return
                await asyncio.sleep(self._window - (now - self._stamps[0]) + 0.05)
