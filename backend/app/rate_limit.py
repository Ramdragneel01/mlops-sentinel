
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
        self._next_prune_at = time.time() + window_seconds

    def _prune_expired(self, now: float) -> None:
        """Remove expired windows to keep memory usage bounded over time."""

        if now < self._next_prune_at:
            return

        expired_keys = [
            key
            for key, (window_start, _) in self._windows.items()
            if now - window_start >= self._window_seconds
        ]
        for key in expired_keys:
            self._windows.pop(key, None)

        self._next_prune_at = now + self._window_seconds

    def allow(self, key: str, limit: int) -> bool:
        """Return True when request can proceed under current window quota."""

        now = time.time()
        with self._lock:
            self._prune_expired(now)
            window_start, count = self._windows[key]
            if now - window_start >= self._window_seconds:
                self._windows[key] = (now, 1)
                return True

            if count >= limit:
                return False

            self._windows[key] = (window_start, count + 1)
            return True

    def clear(self) -> None:
        """Clear limiter state; useful for deterministic testing."""

        with self._lock:
            self._windows.clear()
