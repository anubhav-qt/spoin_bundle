"""Operator read surfaces (B4).

Read-only, authenticated, and mounted only when `settings.env != "production"`
(see `api/main.py`) -- the same gate `routers/dev.py` sits behind. There is no
admin ROLE yet: every authenticated user is equal, so exposing quota spend,
the key count and the model ladder to all of them in production is an info
leak this gate avoids until a real role check exists. Promoting `/admin/*` to
a production surface is a task, not a config flip -- tracked in
docs/tasks/0035.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter

from spoin.api.deps import SessionDep, UserDep
from spoin.api.schemas import QuotaStatusOut
from spoin.core.config import get_settings
from spoin.generation.quota_report import read_quota_status

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/quota", response_model=QuotaStatusOut)
async def quota_status(session: SessionDep, user_id: UserDep) -> QuotaStatusOut:
    """Today's quota-governor state: one row per `(key, model)` cell with its
    daily spend / ceiling / `exhausted_at` / `cooldown_until`, plus the models
    currently parked by `model_unavailable`.

    The three ADR-0065 rollups (`cells_daily_exhausted`,
    `cells_minute_throttled`, `models_parked`) are separate counts by design --
    "ran out of daily budget", "everything throttled this minute" and "every
    model down" are different facts, and collapsing them is the misread the
    ADR exists to prevent.
    """

    return await read_quota_status(session, get_settings(), now=datetime.now(UTC))
