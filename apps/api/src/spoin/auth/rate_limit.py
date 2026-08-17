"""Brute-force protection for `/auth/login` and `/auth/register`.

**In-memory, single-instance.** Unlike the generation quota governor
(`generation/quota.py`), which persists RPD to survive a restart because the
worker runs as separate cron passes, this limiter only needs to survive within
one running API process — an in-memory sliding window is enough, and avoids a
DB round-trip on every auth request. Accepted tradeoff for now: a restart (or
a second replica) resets/splits the count. Revisit if the API is ever run with
more than one replica behind a shared entrypoint.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import HTTPException, status


class RateLimiter:
    """Sliding-window cap on attempts per key (e.g. `f"{ip}:{email}"`)."""

    def __init__(self, max_attempts: int, window_seconds: int) -> None:
        self._max_attempts = max_attempts
        self._window_seconds = window_seconds
        self._attempts: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        """Raises 429 if `key` has exceeded the window; otherwise records this attempt."""
        now = time.monotonic()
        window = self._attempts[key]
        while window and now - window[0] > self._window_seconds:
            window.popleft()

        if len(window) >= self._max_attempts:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many attempts. Try again later.",
            )

        window.append(now)


# One shared instance per process — module-level, not request-scoped, so the
# window actually accumulates across requests.
login_rate_limiter = RateLimiter(max_attempts=10, window_seconds=60)
register_rate_limiter = RateLimiter(max_attempts=5, window_seconds=60)
