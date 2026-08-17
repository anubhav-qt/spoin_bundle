"""The quota governor (ADR-0003 §6) — multi-key rotation.

Reuses the existing `QuotaLedger` table (`day`, `backend`, `requests_spent`) rather
than inventing new state: each rotating key gets its own ledger row via
`backend=f"gemini:{key_index}"`, so multi-key tracking needed no schema change
beyond widening `backend` and adding `exhausted_at` (see the migration).

**Deliberately session-per-call, not session-per-instance.** A `QuotaGovernor`
lives for the lifetime of a `GeminiContentGenerator` (one per generation run,
potentially making many concurrent calls — see `generation/pipeline.py`'s
concurrency semaphore). If it held one long-lived `AsyncSession`, every call would
have to share it, which reintroduces exactly the concurrency hazard the pipeline
was built to avoid (`AsyncSession` isn't safe for concurrent task access). Each
`acquire_key()` call instead opens its OWN short-lived session via
`core.db.session_scope()` and commits immediately — quota bookkeeping is
orthogonal to whatever the pipeline's own transaction does, so there's no reason
to tie them together.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from slocho.core.db import session_scope
from slocho.domain.models.quiz import QuotaLedger


class QuotaExhaustedError(RuntimeError):
    """Every configured key has hit today's target. ADR-0003 §6: this is a real,
    expected outcome to degrade gracefully from — not a try/except accident."""


def _day_start(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


class QuotaGovernor:
    """One instance per `GeminiContentGenerator` (i.e. per generation run).

    `acquire_key(now=...)` atomically checks-and-increments the active key's spend
    for today, rotating to the next key once it hits `daily_target`, and returns
    the index of the key to use for the call about to be made. The internal lock
    only guards the cheap DB check-and-increment — callers make the actual network
    call themselves after this returns, so concurrent calls landing on different
    keys still run concurrently. Concurrent calls landing on the SAME key are what
    the lock actually serializes, which is the race that matters.
    """

    def __init__(self, *, key_count: int, daily_target: int) -> None:
        if key_count < 1:
            raise ValueError("QuotaGovernor needs at least one key")
        if daily_target < 1:
            raise ValueError("daily_target must be at least 1")
        self._key_count = key_count
        self._target = daily_target
        self._active_index = 0
        self._lock = asyncio.Lock()

    async def acquire_key(self, *, now: datetime) -> int:
        async with self._lock, session_scope() as session:
            return await self._acquire_key_locked(session, now=now)

    async def acquire_key_with_session(self, session: AsyncSession, *, now: datetime) -> int:
        """Same as `acquire_key`, but reuses a caller-supplied session instead of
        opening its own — for tests, where the fixture session IS the isolation
        boundary and a second connection would see none of its uncommitted rows."""

        async with self._lock:
            return await self._acquire_key_locked(session, now=now)

    async def _acquire_key_locked(self, session: AsyncSession, *, now: datetime) -> int:
        day = _day_start(now)
        for _ in range(self._key_count):
            ledger = await self._ledger_row(session, day, self._active_index)
            if ledger.requests_spent < self._target:
                ledger.requests_spent += 1
                if ledger.requests_spent >= self._target:
                    ledger.exhausted_at = now
                await session.flush()
                return self._active_index
            self._active_index = (self._active_index + 1) % self._key_count
        raise QuotaExhaustedError(f"All {self._key_count} Gemini key(s) exhausted for {day.date()}")

    async def _ledger_row(
        self, session: AsyncSession, day: datetime, key_index: int
    ) -> QuotaLedger:
        backend = f"gemini:{key_index}"
        row = await session.scalar(
            select(QuotaLedger).where(QuotaLedger.day == day, QuotaLedger.backend == backend)
        )
        if row is None:
            row = QuotaLedger(day=day, backend=backend, requests_spent=0)
            session.add(row)
            await session.flush()
        return row
