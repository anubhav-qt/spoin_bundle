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
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spoin.core.db import session_scope
from spoin.domain.models.quiz import QuotaLedger

logger = logging.getLogger("spoin.generation.quota")

#: The trailing window RPM is measured over. Fixed at 60s (what "requests per
#: minute" means) — not a setting, since it isn't a tuning knob.
_RPM_WINDOW_SECONDS = 60.0
_FLASH_LITE_COOLDOWN_SECONDS = 60.0
_FLASH_LITE_MAX_RESETS = 10


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
    #: (key_index, model) -> a lock serializing the actual network calls on
    #: that ONE cell. `acquire()` grants a cell and returns immediately, so
    #: concurrent tasks routed to the same cell would otherwise all fire their
    #: HTTP calls at once -- a burst the provider's own limiter can reject even
    #: though our sliding window shows room over the full 60s. Cell locks make
    #: same-cell calls queue and wait for the previous one to finish before the
    #: next fires; different cells (independent quota) still run concurrently.
    _cell_locks: dict[tuple[int, str], asyncio.Lock] = field(
        default_factory=dict, init=False, repr=False
    )
    #: (key_index, model) -> timestamp (time.monotonic()) until which flash-lite
    #: cell is cooling off after a 429 before resetting spend to 0.
    _flash_lite_cooldowns: dict[tuple[int, str], float] = field(
        default_factory=dict, init=False, repr=False
    )
    #: (key_index, model) -> number of 60s cooldown resets done today for flash-lite
    _flash_lite_reset_counts: dict[tuple[int, str], int] = field(
        default_factory=lambda: defaultdict(int), init=False, repr=False
    )

    def __post_init__(self) -> None:
        if self.key_count < 1:
            raise ValueError("QuotaGovernor needs at least one key")
        if not self.ladder:
            raise ValueError("QuotaGovernor needs at least one ladder rung")

    async def acquire(
        self, *, now: datetime, exclude_models: frozenset[str] = frozenset()
    ) -> tuple[int, str]:
        async with self._lock, session_scope() as session:
            return await self._acquire_locked(session, now=now, exclude_models=exclude_models)

    async def acquire_with_session(
        self, session: AsyncSession, *, now: datetime, exclude_models: frozenset[str] = frozenset()
    ) -> tuple[int, str]:
        """Same as `acquire`, but reuses a caller-supplied session instead of
        opening its own — for tests, where the fixture session IS the
        isolation boundary and a second connection would see none of its
        uncommitted rows."""

        async with self._lock:
            return await self._acquire_locked(session, now=now, exclude_models=exclude_models)

    async def mark_exhausted(self, key_index: int, model: str, *, now: datetime) -> None:
        """A REAL 429 from the provider disagreed with our local ledger, which
        believed this cell had room (ADR-0028's documented drift risk,
        confirmed live rather than theoretical). Force the ledger to treat
        this cell as exhausted for the rest of today, so the NEXT `acquire()`
        -- ours or a concurrent caller's -- skips it immediately instead of
        rediscovering the same 429 on every subsequent call.

        For flash-lite models, we apply a 60s cooldown and reset spend to 0
        up to 10 times per key before marking it permanently exhausted for today.

        Unknown model (not in this pool's ladder) is a caller bug, not a
        runtime condition to degrade from -- raises rather than silently
        no-op-ing, same posture as `parse_ladder` on a malformed ladder string."""

        async with self._lock, session_scope() as session:
            await self._mark_exhausted_locked(session, key_index, model, now=now)

    async def mark_exhausted_with_session(
        self, session: AsyncSession, key_index: int, model: str, *, now: datetime
    ) -> None:
        """Same as `mark_exhausted`, but reuses a caller-supplied session instead
        of opening its own — for tests, same reasoning as `acquire_with_session`."""

        async with self._lock:
            await self._mark_exhausted_locked(session, key_index, model, now=now)

    async def _mark_exhausted_locked(
        self, session: AsyncSession, key_index: int, model: str, *, now: datetime
    ) -> None:
        rung = next((r for r in self.ladder if r.model == model), None)
        if rung is None:
            raise ValueError(f"mark_exhausted: {model!r} is not in this pool's ladder")

        day = _day_start(now)
        ledger = await self._ledger_row(session, day, key_index, model)

        is_flash_lite = "flash-lite" in model.lower()
        if (
            is_flash_lite
            and self._flash_lite_reset_counts[(key_index, model)] < _FLASH_LITE_MAX_RESETS
        ):
            self._flash_lite_reset_counts[(key_index, model)] += 1
            reset_num = self._flash_lite_reset_counts[(key_index, model)]
            self._flash_lite_cooldowns[(key_index, model)] = (
                time.monotonic() + _FLASH_LITE_COOLDOWN_SECONDS
            )
            ledger.requests_spent = 0
            ledger.exhausted_at = None
            await session.flush()
            logger.warning(
                "quota: key %d flash-lite model %s 429'd -- rotated key, reset spend to 0 "
                "with 60s cooldown (reset %d/%d)",
                key_index,
                model,
                reset_num,
                _FLASH_LITE_MAX_RESETS,
            )
            return

        ledger.requests_spent = max(ledger.requests_spent, rung.rpd)
        ledger.exhausted_at = now
        await session.flush()
        logger.warning(
            "quota: key %d model %s marked exhausted after a REAL 429 from the provider "
            "(local ledger believed it had room)",
            key_index,
            model,
        )

    async def _acquire_locked(
        self, session: AsyncSession, *, now: datetime, exclude_models: frozenset[str] = frozenset()
    ) -> tuple[int, str]:
        """`exclude_models` skips entire ladder rungs (every key) rather than
        one `(key, model)` cell. A real 429 is per-key (ADR-0028's ledger
        tracks it that way), but a 503 "high demand" overload is per-MODEL --
        every key hits the same wall on that model, so cycling through keys
        one at a time on an overloaded model just burns real per-key quota
        for no chance of success. Callers pass the models they've already
        found persistently unavailable this call so acquire() jumps straight
        to the next model instead."""

        day = _day_start(now)
        while True:
            candidate_wait_times: list[float] = []
            has_unexhausted_cell = False

            for rung in self.ladder:
                if rung.model in exclude_models:
                    logger.debug(
                        "quota: model %s excluded (persistently unavailable), skipping", rung.model
                    )
                    continue
                for key_index in range(self.key_count):
                    ledger = await self._ledger_row(session, day, key_index, rung.model)
                    if ledger.requests_spent >= rung.rpd:
                        logger.debug(
                            "quota: key %d model %s already exhausted for %s (%d/%d), trying next",
                            key_index,
                            rung.model,
                            day.date(),
                            ledger.requests_spent,
                            rung.rpd,
                        )
                        continue

                    has_unexhausted_cell = True

                    cooldown_until = self._flash_lite_cooldowns.get((key_index, rung.model))
                    if cooldown_until is not None and time.monotonic() < cooldown_until:
                        wait_cd = cooldown_until - time.monotonic()
                        candidate_wait_times.append(wait_cd)
                        logger.debug(
                            "quota: key %d model %s is in flash-lite cooldown (%.1fs remaining), "
                            "trying next",
                            key_index,
                            rung.model,
                            wait_cd,
                        )
                        continue

                    if not self._rpm_has_room(key_index, rung):
                        window = self._rpm_windows[(key_index, rung.model)]
                        if window:
                            wait_rpm = (window[0] + _RPM_WINDOW_SECONDS) - time.monotonic()
                            if wait_rpm > 0:
                                candidate_wait_times.append(wait_rpm)
                        logger.debug(
                            "quota: key %d model %s at RPM ceiling (%d/min), trying next",
                            key_index,
                            rung.model,
                            rung.rpm,
                        )
                        continue

                    ledger.requests_spent += 1
                    if ledger.requests_spent >= rung.rpd:
                        ledger.exhausted_at = now
                        logger.info(
                            "quota: key %d model %s just hit its RPD ceiling (%d/day) for %s",
                            key_index,
                            rung.model,
                            rung.rpd,
                            day.date(),
                        )
                    await session.flush()
                    self._record_rpm(key_index, rung)
                    logger.info(
                        "quota: acquired key=%d model=%s (%d/%d spent today)",
                        key_index,
                        rung.model,
                        ledger.requests_spent,
                        rung.rpd,
                    )
                    return key_index, rung.model

            if not has_unexhausted_cell:
                logger.warning(
                    "quota: ALL %d key(s) x %d model(s) exhausted for %s",
                    self.key_count,
                    len(self.ladder),
                    day.date(),
                )
                raise QuotaExhaustedError(
                    f"All {self.key_count} key(s) x {len(self.ladder)} model(s) "
                    f"exhausted for {day.date()}"
                )

            # All candidate keys have daily quota remaining but are temporarily rate-limited
            # (in RPM window or 60s flash-lite cooldown). Sleep until the earliest slot opens.
            min_wait = min(candidate_wait_times) if candidate_wait_times else 2.0
            sleep_duration = max(0.5, min(min_wait + 0.2, 60.0))
            logger.info(
                "quota: all available cells at temporary RPM/cooldown limit -- "
                "waiting %.1fs before retrying...",
                sleep_duration,
            )
            await asyncio.sleep(sleep_duration)

    def cell_lock(self, key_index: int, model: str) -> asyncio.Lock:
        """Returns the lock for this `(key, model)` cell, creating it on first
        use. Callers hold this around the actual network call (NOT around
        `acquire()`, which has its own lock) so same-cell calls queue one at a
        time while different cells stay concurrent."""

        cell = (key_index, model)
        lock = self._cell_locks.get(cell)
        if lock is None:
            lock = asyncio.Lock()
            self._cell_locks[cell] = lock
        return lock

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
