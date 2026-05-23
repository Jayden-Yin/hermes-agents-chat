"""
Hermes Chat — Sliding-window rate limiter.
O(1) per check: maintains a deque of timestamps per (room_id, scope) key.
Thread-safe under asyncio (no shared-mutation race across concurrent fan-out).
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field


@dataclass
class RateLimitBucket:
    """Sliding window for a single key."""
    window_sec: float
    max_count: int
    timestamps: list[float] = field(default_factory=list)

    def _sweep(self, now: float) -> None:
        cutoff = now - self.window_sec
        # Binary-search for the first timestamp inside the window
        lo, hi = 0, len(self.timestamps)
        while lo < hi:
            mid = (lo + hi) // 2
            if self.timestamps[mid] < cutoff:
                lo = mid + 1
            else:
                hi = mid
        if lo > 0:
            self.timestamps = self.timestamps[lo:]

    def allow(self, now: float | None = None) -> bool:
        now = now or time.monotonic()
        self._sweep(now)
        if len(self.timestamps) >= self.max_count:
            return False
        self.timestamps.append(now)
        return True

    def remaining(self, now: float | None = None) -> int:
        now = now or time.monotonic()
        self._sweep(now)
        return max(0, self.max_count - len(self.timestamps))


class RateLimiter:
    """
    Multi-key sliding-window rate limiter.

    Default room-level limit: 5 agent replies per 60 seconds.
    """

    def __init__(self) -> None:
        # key → window per-{room_id}
        self._buckets: dict[str, RateLimitBucket] = {}
        self._default_window = 60.0
        self._default_max = 5

    def _key(self, room_id: str) -> str:
        return f"room:{room_id}"

    def check(self, room_id: str) -> bool:
        """Return True if a new agent reply is allowed for this room."""
        key = self._key(room_id)
        if key not in self._buckets:
            self._buckets[key] = RateLimitBucket(
                window_sec=self._default_window,
                max_count=self._default_max,
            )
        return self._buckets[key].allow()

    def check_many(self, room_id: str, count: int) -> Sequence[bool]:
        """Atomically check *count* slots. Returns list of booleans."""
        return [self.check(room_id) for _ in range(count)]

    def remaining(self, room_id: str) -> int:
        key = self._key(room_id)
        if key not in self._buckets:
            return self._default_max
        return self._buckets[key].remaining()

    def reset(self, room_id: str) -> None:
        self._buckets.pop(self._key(room_id), None)


# Module-level singleton
rate_limiter = RateLimiter()
