"""Unit tests for the multi-key quota governor (generation/quota.py).

Pure DB bookkeeping — no real Gemini key needed, no network. Uses the real
`session` fixture (Postgres, skipped if unavailable) since `QuotaLedger` rows and
`day`-scoped uniqueness are the whole point of what's under test.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from slocho.domain.models.quiz import QuotaLedger
from slocho.generation.quota import QuotaExhaustedError, QuotaGovernor


async def test_stays_on_first_key_while_under_target(session: AsyncSession) -> None:
    governor = QuotaGovernor(key_count=3, daily_target=5)
    now = datetime.now(UTC)

    indices = [await governor.acquire_key_with_session(session, now=now) for _ in range(4)]

    assert indices == [0, 0, 0, 0]
    ledger = await session.scalar(select(QuotaLedger).where(QuotaLedger.backend == "gemini:0"))
    assert ledger is not None
    assert ledger.requests_spent == 4
    assert ledger.exhausted_at is None


async def test_rotates_to_next_key_on_exhaustion(session: AsyncSession) -> None:
    governor = QuotaGovernor(key_count=2, daily_target=2)
    now = datetime.now(UTC)

    indices = [await governor.acquire_key_with_session(session, now=now) for _ in range(3)]

    assert indices == [0, 0, 1]
    exhausted = await session.scalar(select(QuotaLedger).where(QuotaLedger.backend == "gemini:0"))
    assert exhausted is not None
    assert exhausted.exhausted_at is not None
    still_open = await session.scalar(select(QuotaLedger).where(QuotaLedger.backend == "gemini:1"))
    assert still_open is not None
    assert still_open.exhausted_at is None


async def test_raises_once_every_key_is_exhausted(session: AsyncSession) -> None:
    governor = QuotaGovernor(key_count=2, daily_target=1)
    now = datetime.now(UTC)

    await governor.acquire_key_with_session(session, now=now)
    await governor.acquire_key_with_session(session, now=now)

    with pytest.raises(QuotaExhaustedError):
        await governor.acquire_key_with_session(session, now=now)


async def test_separate_days_get_separate_ledger_rows(session: AsyncSession) -> None:
    governor = QuotaGovernor(key_count=1, daily_target=2)
    day_one = datetime(2026, 8, 17, 10, 0, tzinfo=UTC)
    day_two = datetime(2026, 8, 18, 10, 0, tzinfo=UTC)

    await governor.acquire_key_with_session(session, now=day_one)
    await governor.acquire_key_with_session(session, now=day_one)
    # Day one's key is exhausted, but day two is a fresh ledger row — same key
    # index, different day, should NOT raise.
    index = await governor.acquire_key_with_session(session, now=day_two)

    assert index == 0
    rows = (await session.execute(select(QuotaLedger))).scalars().all()
    assert len(rows) == 2
