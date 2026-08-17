"""The quota governor (ADR-0003 §6, redesigned per ADR-0028) — a key x model
grid, not a flat list of keys.

Gemini rate limits are per-project, not per-key (ADR-0028's finding) — so each
entry in `SPOIN_GEMINI_API_KEYS` is assumed to be its own project, and each
model in a ladder has its OWN daily/per-minute limit, independent of every
other model. `QuotaGovernor` walks that grid: for a call, try the strongest
model in the ladder across every configured key; only fall to the next model
once every key is exhausted for the current one.

**RPD is persisted, RPM is not.** `QuotaLedger` (day, backend, requests_spent)
tracks the daily count per `(key_index, model)` — `backend=f"gemini:{key_index}:
{model}"` — because it must survive across the worker's separate cron passes
within the same day. The per-minute count does NOT need to survive a restart:
the worker is a short-lived batch pass (ADR-0003 §3), not a persistent
process, so an in-memory sliding window that resets every run is sufficient
and avoids a DB round-trip per request just to enforce RPM.

**Deliberately session-per-call, not session-per-instance.** A `QuotaGovernor`
lives for the lifetime of a `GeminiContentGenerator` (one per generation run,
potentially making many concurrent calls — see `generation/pipeline.py`'s
concurrency semaphore). If it held one long-lived `AsyncSession`, every call
would have to share it, which reintroduces exactly the concurrency hazard the
pipeline was built to avoid (`AsyncSession` isn't safe for concurrent task
access). Each `acquire()` call instead opens its OWN short-lived session via
`core.db.session_scope()` and commits immediately.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spoin.core.db import session_scope
from spoin.domain.models.quiz import QuotaLedger

#: The trailing window RPM is measured over. Fixed at 60s (what "requests per
#: minute" means) — not a setting, since it isn't a tuning knob.
_RPM_WINDOW_SECONDS = 60.0


class QuotaExhaustedError(RuntimeError):
    """Every key is exhausted for every model in the ladder, for today.

    ADR-0003 §6: this is a real, expected outcome to degrade gracefully from —
    not a try/except accident. The worker (`apps/worker/__main__.py`) catches
    this specifically and requeues the job as `pending` rather than `failed`,
    since `run_generation_pipeline` is idempotent (ADR-0026) and safely
    resumes once quota resets.
    """


@dataclass(frozen=True)
class LadderRung:
    """One model's place in a fallback ladder, and its own daily/per-minute
    caps — read straight off the provider's rate-limit page for the key in
    use. Order in the parent list IS priority: index 0 is tried first."""

    model: str
    rpd: int
    rpm: int


def parse_ladder(raw: str) -> list[LadderRung]:
    """Parses `"model:rpd:rpm,model:rpd:rpm,..."` (see Settings.gemini_*_ladder).

    A plain string, not a structured setting, for the same reason
    `cors_origins`/`gemini_api_keys` are: pydantic-settings JSON-parses
    list-typed env vars, which breaks an ordinary comma-separated value.
    """

    rungs: list[LadderRung] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        model, rpd, rpm = part.split(":")
        rungs.append(LadderRung(model=model, rpd=int(rpd), rpm=int(rpm)))
    if not rungs:
        raise ValueError("Model ladder must have at least one rung")
    return rungs


def _day_start(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


@dataclass
class QuotaGovernor:
    """One instance per pool (e.g. "thinking" vs "cards") per
    `GeminiContentGenerator`. `acquire(now=...)` returns `(key_index, model)`
    for the next call to make: the highest-priority ladder rung that still has
    room, checked across every key before falling to the next rung.

    The lock only guards the cheap DB check-and-increment plus the in-memory
    RPM check — callers make the actual network call themselves after this
    returns, so concurrent calls landing on different `(key, model)` cells
    still run concurrently. Concurrent calls racing for the SAME cell are what
    the lock actually serializes.
    """

    key_count: int
    ladder: list[LadderRung]
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
    #: (key_index, model) -> timestamps (time.monotonic()) of calls within the
    #: trailing RPM window. In-memory only — see module docstring.
    _rpm_windows: dict[tuple[int, str], deque[float]] = field(
        default_factory=lambda: defaultdict(deque), init=False, repr=False
    )

    def __post_init__(self) -> None:
        if self.key_count < 1:
            raise ValueError("QuotaGovernor needs at least one key")
        if not self.ladder:
            raise ValueError("QuotaGovernor needs at least one ladder rung")

    async def acquire(self, *, now: datetime) -> tuple[int, str]:
        async with self._lock, session_scope() as session:
            return await self._acquire_locked(session, now=now)

    async def acquire_with_session(
        self, session: AsyncSession, *, now: datetime
    ) -> tuple[int, str]:
        """Same as `acquire`, but reuses a caller-supplied session instead of
        opening its own — for tests, where the fixture session IS the
        isolation boundary and a second connection would see none of its
        uncommitted rows."""

        async with self._lock:
            return await self._acquire_locked(session, now=now)

    async def _acquire_locked(self, session: AsyncSession, *, now: datetime) -> tuple[int, str]:
        day = _day_start(now)
        for rung in self.ladder:
            for key_index in range(self.key_count):
                if not self._rpm_has_room(key_index, rung):
                    continue
                ledger = await self._ledger_row(session, day, key_index, rung.model)
                if ledger.requests_spent < rung.rpd:
                    ledger.requests_spent += 1
                    if ledger.requests_spent >= rung.rpd:
                        ledger.exhausted_at = now
                    await session.flush()
                    self._record_rpm(key_index, rung)
                    return key_index, rung.model
        raise QuotaExhaustedError(
            f"All {self.key_count} key(s) x {len(self.ladder)} model(s) exhausted for {day.date()}"
        )

    def _rpm_has_room(self, key_index: int, rung: LadderRung) -> bool:
        window = self._rpm_windows[(key_index, rung.model)]
        cutoff = time.monotonic() - _RPM_WINDOW_SECONDS
        while window and window[0] < cutoff:
            window.popleft()
        return len(window) < rung.rpm

    def _record_rpm(self, key_index: int, rung: LadderRung) -> None:
        self._rpm_windows[(key_index, rung.model)].append(time.monotonic())

    async def _ledger_row(
        self, session: AsyncSession, day: datetime, key_index: int, model: str
    ) -> QuotaLedger:
        backend = f"gemini:{key_index}:{model}"
        row = await session.scalar(
            select(QuotaLedger).where(QuotaLedger.day == day, QuotaLedger.backend == backend)
        )
        if row is None:
            row = QuotaLedger(day=day, backend=backend, requests_spent=0)
            session.add(row)
            await session.flush()
        return row
