"""Unit tests for the key x model quota governor (generation/quota.py, ADR-0028).

Pure DB bookkeeping — no real Gemini key needed, no network. Uses the real
`session` fixture (Postgres, skipped if unavailable) since `QuotaLedger` rows and
`day`-scoped uniqueness are the whole point of what's under test. RPM is
in-memory only, so those tests don't touch the database at all — they rely on
calls happening well within one 60s window, never on real sleeping.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spoin.domain.models.quiz import QuotaLedger
from spoin.generation.quota import LadderRung, QuotaExhaustedError, QuotaGovernor, parse_ladder


def _ladder(*rungs: tuple[str, int, int]) -> list[LadderRung]:
    return [LadderRung(model=model, rpd=rpd, rpm=rpm) for model, rpd, rpm in rungs]


async def test_stays_on_first_key_and_model_while_under_target(session: AsyncSession) -> None:
    governor = QuotaGovernor(key_count=3, ladder=_ladder(("model-a", 5, 100)))
    now = datetime.now(UTC)

    results = [await governor.acquire_with_session(session, now=now) for _ in range(4)]

    assert results == [(0, "model-a")] * 4
    ledger = await session.scalar(
        select(QuotaLedger).where(QuotaLedger.backend == "gemini:0:model-a")
    )
    assert ledger is not None
    assert ledger.requests_spent == 4
    assert ledger.exhausted_at is None


async def test_drains_every_key_before_falling_to_the_next_model(session: AsyncSession) -> None:
    governor = QuotaGovernor(key_count=2, ladder=_ladder(("model-a", 2, 100), ("model-b", 2, 100)))
    now = datetime.now(UTC)

    results = [await governor.acquire_with_session(session, now=now) for _ in range(5)]

    # Both keys exhaust model-a (2 each) before model-b is ever touched.
    assert results == [
        (0, "model-a"),
        (0, "model-a"),
        (1, "model-a"),
        (1, "model-a"),
        (0, "model-b"),
    ]
    exhausted = await session.scalar(
        select(QuotaLedger).where(QuotaLedger.backend == "gemini:1:model-a")
    )
    assert exhausted is not None
    assert exhausted.exhausted_at is not None


async def test_rpm_ceiling_skips_to_the_next_key_without_waiting(session: AsyncSession) -> None:
    # Huge RPD, tiny RPM -- the second call within the same instant should
    # skip key 0 (already at its 1-per-minute ceiling) rather than wait.
    governor = QuotaGovernor(key_count=2, ladder=_ladder(("model-a", 100, 1)))
    now = datetime.now(UTC)

    first = await governor.acquire_with_session(session, now=now)
    second = await governor.acquire_with_session(session, now=now)

    assert first == (0, "model-a")
    assert second == (1, "model-a")


async def test_mark_exhausted_forces_a_cell_off_the_ladder(session: AsyncSession) -> None:
    """A real 429 from the provider disagreeing with our local ledger (the
    ADR-0028 drift risk) -- mark_exhausted must make the NEXT acquire() skip
    that cell, even though the ledger only recorded 0 requests against it."""

    governor = QuotaGovernor(key_count=2, ladder=_ladder(("model-a", 20, 100)))
    now = datetime.now(UTC)

    await governor.mark_exhausted_with_session(session, 0, "model-a", now=now)
    ledger = await session.scalar(
        select(QuotaLedger).where(QuotaLedger.backend == "gemini:0:model-a")
    )
    assert ledger is not None
    assert ledger.requests_spent >= 20
    assert ledger.exhausted_at is not None

    result = await governor.acquire_with_session(session, now=now)
    assert result == (1, "model-a")


async def test_raises_once_every_key_and_model_exhausted(session: AsyncSession) -> None:
    governor = QuotaGovernor(key_count=2, ladder=_ladder(("model-a", 1, 100)))
    now = datetime.now(UTC)

    await governor.acquire_with_session(session, now=now)
    await governor.acquire_with_session(session, now=now)

    with pytest.raises(QuotaExhaustedError):
        await governor.acquire_with_session(session, now=now)


async def test_separate_days_get_separate_ledger_rows(session: AsyncSession) -> None:
    governor = QuotaGovernor(key_count=1, ladder=_ladder(("model-a", 2, 100)))
    day_one = datetime(2026, 8, 17, 10, 0, tzinfo=UTC)
    day_two = datetime(2026, 8, 18, 10, 0, tzinfo=UTC)

    await governor.acquire_with_session(session, now=day_one)
    await governor.acquire_with_session(session, now=day_one)
    # Day one's key is exhausted, but day two is a fresh ledger row — same
    # key/model, different day, should NOT raise.
    result = await governor.acquire_with_session(session, now=day_two)

    assert result == (0, "model-a")
    rows = (await session.execute(select(QuotaLedger))).scalars().all()
    assert len(rows) == 2


def test_parse_ladder_reads_model_rpd_rpm_triples() -> None:
    rungs = parse_ladder("gemini-3.7-flash:20:5, gemini-2.5-flash:20:5")
    assert rungs == [
        LadderRung(model="gemini-3.7-flash", rpd=20, rpm=5),
        LadderRung(model="gemini-2.5-flash", rpd=20, rpm=5),
    ]


def test_parse_ladder_rejects_empty_string() -> None:
    with pytest.raises(ValueError, match="at least one rung"):
        parse_ladder("")


def test_governor_rejects_empty_ladder() -> None:
    with pytest.raises(ValueError, match="at least one ladder rung"):
        QuotaGovernor(key_count=1, ladder=[])
