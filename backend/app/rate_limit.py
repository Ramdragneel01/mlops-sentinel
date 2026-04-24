
"""Simple in-memory fixed-window rate limiter utilities."""

from __future__ import annotations

from collections import defaultdict
import threading
import time


class InMemoryRateLimiter:
    """Tracks request counts in a fixed time window per client key."""

    def __init__(self, window_seconds: int = 60) -> None:
        """Initialize rate limiter with configurable fixed window size."""

        self._window_seconds = window_seconds
        self._lock = threading.Lock()
        self._windows: dict[str, tuple[float, int]] = defaultdict(lambda: (0.0, 0))

    def allow(self, key: str, limit: int) -> bool:
        """Return True when request can proceed under current window quota."""

        now = time.time()
        with self._lock:
            window_start, count = self._windows[key]
            if now - window_start >= self._window_seconds:
                self._windows[key] = (now, 1)
                return True

            if count >= limit:
                return False

            self._windows[key] = (window_start, count + 1)
            return True
