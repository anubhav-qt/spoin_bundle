"""GET /admin/quota — the quota read surface (B4).

Real `session` fixture: `quota_ledger` / `model_unavailable` rows and the
`(day, backend)` key are the whole point. No network — `read_quota_status` only
reads three tables and the configured ladders.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from spoin.core.config import Settings
from spoin.domain.models.quiz import ModelUnavailable, QuotaLedger
from spoin.generation.quota import _backend, _day_start
from spoin.generation.quota_report import read_quota_status

# Two keys, one rung per pool — small enough to assert the whole grid.
_SETTINGS = Settings(
    _env_file=None,
    gemini_api_keys="key-a,key-b",
    gemini_thinking_ladder="think-model:20:5",
    gemini_generator_ladder="lite-model:500:15",
)


async def test_grid_covers_every_key_times_model_even_with_no_ledger_rows(
    session: AsyncSession,
) -> None:
    now = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)

    status = await read_quota_status(session, _SETTINGS, now=now)

    # 2 keys x 2 models = 4 cells, all untouched.
    assert status.cells_total == 4
    assert {(c.key_index, c.model, c.pool) for c in status.cells} == {
        (0, "think-model", "thinking"),
        (1, "think-model", "thinking"),
        (0, "lite-model", "generator"),
        (1, "lite-model", "generator"),
    }
    assert all(c.requests_spent == 0 for c in status.cells)
    assert {c.daily_ceiling for c in status.cells} == {20, 500}
    assert status.cells_daily_exhausted == 0
    assert status.cells_minute_throttled == 0
    assert status.models_parked == 0


async def test_ledger_spend_and_the_three_rollups_stay_distinct(session: AsyncSession) -> None:
    now = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    day = _day_start(now)

    session.add_all(
        [
            # Daily budget gone for this cell.
            QuotaLedger(
                day=day,
                backend=_backend(0, "think-model"),
                requests_spent=20,
                exhausted_at=now - timedelta(minutes=5),
            ),
            # Per-minute throttled, daily headroom remains.
            QuotaLedger(
                day=day,
                backend=_backend(1, "lite-model"),
                requests_spent=120,
                cooldown_until=now + timedelta(seconds=30),
            ),
            # A stale cooldown that has already passed -> not counted.
            QuotaLedger(
                day=day,
                backend=_backend(0, "lite-model"),
                requests_spent=3,
                cooldown_until=now - timedelta(seconds=30),
            ),
        ]
    )
    session.add(
        ModelUnavailable(
            model="think-model",
            excluded_at=now - timedelta(minutes=1),
            expires_at=now + timedelta(minutes=10),
            reason="503 overloaded",
        )
    )
    await session.flush()

    status = await read_quota_status(session, _SETTINGS, now=now)

    assert status.cells_daily_exhausted == 1
    assert status.cells_minute_throttled == 1
    assert status.models_parked == 1
    # The three are independent counts, never folded together.
    spent = {c.backend: c.requests_spent for c in status.cells}
    assert spent[_backend(0, "think-model")] == 20
    assert spent[_backend(1, "lite-model")] == 120
    assert spent[_backend(0, "lite-model")] == 3  # stale-cooldown cell, still shown

    parked = status.parked_models
    assert len(parked) == 1
    assert parked[0].reason == "503 overloaded"


async def test_ledger_row_outside_the_configured_grid_is_still_shown(session: AsyncSession) -> None:
    now = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    day = _day_start(now)

    # A model no longer in any ladder, from an earlier run.
    session.add(QuotaLedger(day=day, backend=_backend(0, "retired-model"), requests_spent=17))
    await session.flush()

    status = await read_quota_status(session, _SETTINGS, now=now)

    extra = [c for c in status.cells if c.model == "retired-model"]
    assert len(extra) == 1
    assert extra[0].pool == "other"
    assert extra[0].daily_ceiling is None
    assert extra[0].requests_spent == 17
    # 4 grid cells + 1 orphan.
    assert status.cells_total == 5


async def test_only_todays_ledger_rows_are_read(session: AsyncSession) -> None:
    now = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    yesterday = _day_start(now - timedelta(days=1))

    session.add(
        QuotaLedger(
            day=yesterday,
            backend=_backend(0, "think-model"),
            requests_spent=20,
            exhausted_at=yesterday + timedelta(hours=3),
        )
    )
    await session.flush()

    status = await read_quota_status(session, _SETTINGS, now=now)

    # Yesterday's exhaustion does not bleed into today's view.
    assert status.cells_daily_exhausted == 0
    assert all(c.requests_spent == 0 for c in status.cells)
