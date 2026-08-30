"""A read-only view of the quota governor's state (B4).

Separate from `quota.py` on purpose: nothing here grants, reserves or mutates a
cell. It reads today's `quota_ledger`, the live `model_unavailable` rows and the
configured ladders, and assembles them into `QuotaStatusOut` for
`GET /admin/quota`.

The one rule this module exists to hold: ADR-0065's three terminal conditions
stay SEPARATE. "The daily budget is gone", "every cell is per-minute throttled"
and "every model is unavailable" are different facts with different cures, and a
status surface that ORs them into one "exhausted" recreates exactly the misread
the ADR was written to prevent. The rollup fields are three independent counts,
never a single boolean.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spoin.api.schemas import ParkedModelOut, QuotaCellOut, QuotaStatusOut
from spoin.core.config import Settings
from spoin.domain.models.quiz import ModelUnavailable, QuotaLedger
from spoin.generation.quota import _backend, _day_start, parse_ladder

#: Same order the generator uses (`GeminiContentGenerator`): the thinking pool
#: drives curriculum/judging, the generator pool drives cards/questions.
_POOLS: tuple[tuple[str, str], ...] = (
    ("thinking", "gemini_thinking_ladder"),
    ("generator", "gemini_generator_ladder"),
)


def _split_backend(backend: str) -> tuple[int, str]:
    """`gemini:{key_index}:{model}` -> `(key_index, model)`. A legacy
    single-token backend (pre-key-awareness -- see `QuotaLedger.backend`) has no
    key index; report it as -1 so it still shows up rather than being dropped."""

    parts = backend.split(":", 2)
    if len(parts) == 3 and parts[1].isdigit():
        return int(parts[1]), parts[2]
    return -1, backend


async def read_quota_status(
    session: AsyncSession, settings: Settings, *, now: datetime
) -> QuotaStatusOut:
    day = _day_start(now)

    ledger_by_backend = {
        row.backend: row
        for row in (await session.execute(select(QuotaLedger).where(QuotaLedger.day == day)))
        .scalars()
        .all()
    }

    # The configured (key x model) grid: every cell that CAN be spent today,
    # whether or not it has a ledger row yet.
    ceiling_by_model: dict[str, int] = {}
    pool_by_model: dict[str, str] = {}
    for pool, setting_name in _POOLS:
        for rung in parse_ladder(getattr(settings, setting_name)):
            ceiling_by_model.setdefault(rung.model, rung.rpd)
            pool_by_model.setdefault(rung.model, pool)

    key_count = len(settings.gemini_api_key_list)

    cells: list[QuotaCellOut] = []
    covered: set[str] = set()
    for key_index in range(key_count):
        for model, ceiling in ceiling_by_model.items():
            backend = _backend(key_index, model)
            covered.add(backend)
            row = ledger_by_backend.get(backend)
            cells.append(
                QuotaCellOut(
                    backend=backend,
                    key_index=key_index,
                    model=model,
                    pool=pool_by_model[model],
                    requests_spent=row.requests_spent if row else 0,
                    daily_ceiling=ceiling,
                    exhausted_at=row.exhausted_at if row else None,
                    cooldown_until=row.cooldown_until if row else None,
                )
            )

    # Ledger rows outside that grid: a model dropped from a ladder, or a run
    # made against more keys than are configured now. Still real spend -- show
    # it rather than hide it.
    for backend, row in ledger_by_backend.items():
        if backend in covered:
            continue
        key_index, model = _split_backend(backend)
        cells.append(
            QuotaCellOut(
                backend=backend,
                key_index=key_index,
                model=model,
                pool=pool_by_model.get(model, "other"),
                requests_spent=row.requests_spent,
                daily_ceiling=ceiling_by_model.get(model),
                exhausted_at=row.exhausted_at,
                cooldown_until=row.cooldown_until,
            )
        )

    cells.sort(key=lambda c: (c.pool, c.key_index, c.model))

    parked = [
        ParkedModelOut(
            model=row.model,
            excluded_at=row.excluded_at,
            expires_at=row.expires_at,
            reason=row.reason,
        )
        for row in (await session.execute(select(ModelUnavailable))).scalars().all()
    ]

    return QuotaStatusOut(
        day=day,
        generated_at=now,
        cells=cells,
        parked_models=parked,
        cells_total=len(cells),
        cells_daily_exhausted=sum(1 for c in cells if c.exhausted_at is not None),
        cells_minute_throttled=sum(
            1 for c in cells if c.cooldown_until is not None and c.cooldown_until > now
        ),
        models_parked=len(parked),
    )
