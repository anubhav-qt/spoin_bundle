"""The quota governor (ADR-0003 §6, redesigned per ADR-0028) — a key x model
grid, not a flat list of keys.

Gemini rate limits are per-project, not per-key (ADR-0028's finding) — so each
entry in `SPOIN_GEMINI_API_KEYS` is assumed to be its own project, and each
model in a ladder has its OWN daily/per-minute limit, independent of every
other model. `QuotaGovernor` walks that grid: for a call, try the strongest
model in the ladder across every configured key; only fall to the next model
once every key is exhausted for the current one.

**Both RPD and RPM are persisted** — `QuotaLedger` (day, backend,
requests_spent, cooldown_until) for the day, `QuotaRequest` (backend, sent_at)
for the trailing minute, both keyed on `f"gemini:{key_index}:{model}"`.

RPM used to be an in-memory sliding window, on the reasoning that a short-lived
batch worker (ADR-0003 §3) doesn't need it to survive a restart, and that a DB
round-trip per request was too much to pay. The first half is still true and is
not the point: the problem was never restarts, it was **concurrent processes**.
The API (topic matching, quiz grading) and the worker both draw on the thinking
pool at the same time, and an in-memory window means each one independently
permits the full ceiling — so the provider sees double what either believes it
sent, and 429s arrive that neither can explain. ADR-0058 has the reasoning and
the measurements; the short version is that the round-trip objection turned out
to be small next to `acquire()`'s existing per-cell ledger reads, and correctness
across processes is worth more than saving one query.

**These rows are disposable, unlike the ledger's.** A `QuotaRequest` matters for
60 seconds; `prune_request_window` drops them opportunistically from `acquire()`.
They are read once more on the way out, though: a row still `confirmed=False`
that late marks a cell billed for a call that never happened, and the prune
refunds it (ADR-0061 -- see `prune_request_window`).

**Deliberately session-per-call, not session-per-instance.** A `QuotaGovernor`
lives for the lifetime of a `GeminiContentGenerator` (one per generation run,
potentially making many concurrent calls — since ADR-0047 removed the old
global semaphore, this governor IS the only thing bounding that concurrency).
If it held one long-lived `AsyncSession`, every call
would have to share it, which reintroduces exactly the concurrency hazard the
pipeline was built to avoid (`AsyncSession` isn't safe for concurrent task
access). Each `acquire()` call instead opens its OWN short-lived session via
`core.db.session_scope()` and commits immediately.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import delete, func, insert, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from spoin.core.db import session_scope
from spoin.domain.models.quiz import QuotaLedger, QuotaRequest

logger = logging.getLogger("spoin.generation.quota")

#: The trailing window RPM is measured over. Fixed at 60s (what "requests per
#: minute" means) — not a setting, since it isn't a tuning knob.
_RPM_WINDOW_SECONDS = 60.0
#: Fallback cooldown for a per-minute 429 that arrived without a `RetryInfo`
#: hint. One full RPM window is the longest a per-minute limit can possibly
#: last, so waiting it out is correct by definition rather than a tuned guess.
_DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS = _RPM_WINDOW_SECONDS
#: How long a `QuotaRequest` row is kept before the opportunistic prune drops it.
#: Deliberately a multiple of the window rather than equal to it: a row is
#: useless once it ages out, but deleting it the instant it does would race the
#: readers still counting it. The margin doubles as the grace period behind
#: `prune_request_window`'s phantom refund -- it is what makes "still
#: unconfirmed" mean "never sent" rather than "sent, slowly".
_REQUEST_RETENTION_SECONDS = _RPM_WINDOW_SECONDS * 5


def _backend(key_index: int, model: str) -> str:
    """The `(key, model)` cell's key in both quota tables. One spelling, one
    place -- `QuotaLedger` and `QuotaRequest` describe the same cell on two
    different time horizons and must agree on how it is named."""

    return f"gemini:{key_index}:{model}"


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

    The lock only guards the cheap DB check-and-increment (RPD ledger, RPM
    reservation) within THIS process — callers make the actual network call
    themselves after this returns, so concurrent calls landing on different
    `(key, model)` cells still run concurrently. Concurrent calls racing for
    the SAME cell within one process are what the lock actually serializes;
    across processes, `_try_reserve_rpm`'s atomic `INSERT ... WHERE` is what
    does the equivalent job (ADR-0058) — there is no cross-process lock.
    """

    key_count: int
    ladder: list[LadderRung]
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
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
    #: Models currently believed unavailable after a client-side timeout
    #: (`langchain_impl.py`'s `DeadlineExceeded` handler) -- excluded from
    #: `acquire()` entirely while a background probe (`_probe_model`) checks
    #: whether they've come back. In-memory only, same posture as the
    #: cooldown/RPM state above: this is a live-availability signal, not a
    #: persisted fact, and doesn't need to survive a restart.
    _excluded_models: set[str] = field(default_factory=set, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.key_count < 1:
            raise ValueError("QuotaGovernor needs at least one key")
        if not self.ladder:
            raise ValueError("QuotaGovernor needs at least one ladder rung")

    async def acquire(
        self, *, now: datetime, exclude_models: frozenset[str] = frozenset()
    ) -> tuple[int, str]:
        async with self._lock, session_scope() as session:
            await self.prune_request_window(session, now=now)
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

    async def mark_rate_limited(
        self, key_index: int, model: str, *, now: datetime, retry_after_s: float | None = None
    ) -> None:
        """A PER-MINUTE 429 (`GenerateRequestsPerMinutePerProjectPerModel`) --
        this cell has daily quota left and is simply being throttled right now.

        Deliberately does NOT touch `requests_spent` (ADR-0058). That column is
        the day's real consumption; writing to it here is what made a burst of
        per-minute throttling read back as "every key exhausted for today"
        while the real daily quota sat untouched. All this does is park the
        cell until `retry_after_s` has passed, which `_acquire_locked` already
        knows how to wait out via its `candidate_wait_times` queue.

        Persisted rather than in-memory so that a throttle ONE process discovers
        is not something every other process has to rediscover the hard way, by
        routing its next call into the same wall.

        Deliberately does not take `self._lock`: `acquire()` holds that across
        its own `asyncio.sleep`, so waiting for it here would make the caller
        that just got throttled queue behind a sleeper before it could record
        the very cooldown that sleeper is waiting to see. The database
        serializes the write on its own; the lock buys nothing."""

        delay = retry_after_s if retry_after_s is not None else _DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS
        async with session_scope() as session:
            await self._mark_rate_limited_with_session(
                session, key_index, model, now=now, delay=delay
            )

    async def mark_rate_limited_with_session(
        self,
        session: AsyncSession,
        key_index: int,
        model: str,
        *,
        now: datetime,
        retry_after_s: float | None = None,
    ) -> None:
        """Same as `mark_rate_limited`, reusing a caller-supplied session — for
        tests, same reasoning as `acquire_with_session`."""

        delay = retry_after_s if retry_after_s is not None else _DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS
        await self._mark_rate_limited_with_session(session, key_index, model, now=now, delay=delay)

    async def _mark_rate_limited_with_session(
        self, session: AsyncSession, key_index: int, model: str, *, now: datetime, delay: float
    ) -> None:
        ledger = await self._ledger_row(session, _day_start(now), key_index, model)
        ledger.cooldown_until = now + timedelta(seconds=delay)
        await session.flush()
        logger.info(
            "quota: key %d model %s hit a per-minute rate limit -- cooling down %.1fs "
            "(daily ledger untouched)",
            key_index,
            model,
            delay,
        )

    async def mark_exhausted(self, key_index: int, model: str, *, now: datetime) -> None:
        """This cell is spent for the rest of TODAY -- a per-day 429, an auth
        failure, or a model that never came back from a recovery probe. Force
        the ledger to treat it as exhausted so the NEXT `acquire()` -- ours or
        a concurrent caller's -- skips it immediately instead of rediscovering
        the same failure on every subsequent call.

        Only ever called for genuinely day-long conditions. A per-minute 429
        goes to `mark_rate_limited` instead; conflating the two is the bug
        ADR-0058 exists to fix.

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

        while True:
            day = _day_start(now)
            candidate_wait_times: list[float] = []
            has_unexhausted_cell = False

            for rung in self.ladder:
                if rung.model in exclude_models:
                    logger.debug("quota: model %s excluded for this call, skipping", rung.model)
                    continue
                if rung.model in self._excluded_models:
                    logger.debug(
                        "quota: model %s excluded pending a recovery probe, skipping", rung.model
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

                    if ledger.cooldown_until is not None and now < ledger.cooldown_until:
                        wait_cd = (ledger.cooldown_until - now).total_seconds()
                        candidate_wait_times.append(wait_cd)
                        logger.debug(
                            "quota: key %d model %s is in a rate-limit cooldown (%.1fs "
                            "remaining), trying next",
                            key_index,
                            rung.model,
                            wait_cd,
                        )
                        continue

                    # Claims the RPM slot as part of the same check -- see
                    # `_try_reserve_rpm` for why those cannot be two statements.
                    if not await self._try_reserve_rpm(session, key_index, rung, now=now):
                        earliest = await self._earliest_send_in_window(
                            session, key_index, rung.model, now=now
                        )
                        if earliest is not None:
                            wait_rpm = (
                                earliest + timedelta(seconds=_RPM_WINDOW_SECONDS) - now
                            ).total_seconds()
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
            # (our own RPM window, or a provider-signalled cooldown from a per-minute 429).
            # Sleep until the earliest slot opens.
            min_wait = min(candidate_wait_times) if candidate_wait_times else 2.0
            sleep_duration = max(0.5, min(min_wait + 0.2, 60.0))
            logger.info(
                "quota: all available cells at temporary RPM/cooldown limit -- "
                "waiting %.1fs before retrying...",
                sleep_duration,
            )
            await asyncio.sleep(sleep_duration)
            # `now` has to advance by (about) what we just slept, or every check
            # above compares against the same instant forever and this loop
            # never terminates -- confirmed live: it hung for real, in a test,
            # for exactly this reason (a caller-fixed `now` re-entering the
            # RPM/cooldown checks unchanged). Advancing by the slept duration
            # rather than re-reading the wall clock keeps this loop's progress
            # deterministic in terms of what it waited for, not what else the
            # process happened to be doing meanwhile.
            now = now + timedelta(seconds=sleep_duration)

    def exclude_model(self, model: str) -> None:
        """Stop routing real traffic to `model` -- called the moment a call
        times out (see langchain_impl.py's `DeadlineExceeded` handler), before
        the background probe even starts, so nothing else pays that same
        timeout while recovery is being checked."""
        self._excluded_models.add(model)

    def include_model(self, model: str) -> None:
        """Reverses `exclude_model` -- called by the probe either on success
        (model responded again) or once it gives up (every key it tried is
        separately marked exhausted via `mark_exhausted`, so the ledger itself
        keeps those cells out of rotation for the rest of today; releasing the
        flag here only matters for any key the probe didn't get to)."""
        self._excluded_models.discard(model)

    async def record_probe_attempt(self, key_index: int, model: str, *, now: datetime) -> None:
        """One background-probe call against `(key_index, model)` -- counts
        against today's ledger AND the per-minute window, exactly like a real
        acquired call. A probe is not free reconnaissance; it is one real
        request against the provider's limits, so it must be accounted for the
        same way. Reserving the RPM slot here (the probe confirms it with
        `note_request_sent` when the ping actually goes out) is what keeps probe
        traffic from being invisible to real traffic's ceiling -- the probe
        deliberately does not ASK for room, but everything else has to know it
        took some."""

        async with self._lock, session_scope() as session:
            await self._record_probe_attempt_locked(session, key_index, model, now=now)

    async def record_probe_attempt_with_session(
        self, session: AsyncSession, key_index: int, model: str, *, now: datetime
    ) -> None:
        """Same as `record_probe_attempt`, but reuses a caller-supplied session
        instead of opening its own — for tests, same reasoning as
        `acquire_with_session`."""

        async with self._lock:
            await self._record_probe_attempt_locked(session, key_index, model, now=now)

    async def _record_probe_attempt_locked(
        self, session: AsyncSession, key_index: int, model: str, *, now: datetime
    ) -> None:
        rung = next((r for r in self.ladder if r.model == model), None)
        if rung is None:
            raise ValueError(f"record_probe_attempt: {model!r} is not in this pool's ladder")
        day = _day_start(now)
        ledger = await self._ledger_row(session, day, key_index, model)
        ledger.requests_spent += 1
        await session.flush()
        # Reserved unconditionally, not via `_try_reserve_rpm`: a probe does not
        # ASK for room (it is a deliberate availability check, not queued work),
        # but everything else still has to see that it took some.
        session.add(QuotaRequest(backend=_backend(key_index, model), sent_at=now, confirmed=False))
        await session.flush()

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

    async def note_request_sent(self, key_index: int, model: str, *, now: datetime) -> None:
        """The request for this cell is going out to the provider RIGHT NOW.

        `acquire()` reserves a slot when it *grants* a cell, but the call fires
        later -- the caller still has to win `cell_lock`, which queues behind any
        other call on the same cell. Under a parallel fan-out that gap is real
        seconds, and it is what pulls our 60s window out of alignment with the
        provider's: we would count a request in the minute it was reserved while
        the provider counted it in the minute it arrived. Both then believe
        they are under the ceiling, and the provider is the one that's right.

        So the reservation is moved forward to the true send time. The row is
        updated in place rather than replaced, so the count is unchanged and
        only the moment it leaves the window moves -- always later, which is the
        conservative direction.

        With no reservation outstanding this inserts one already-confirmed --
        the right answer for a genuine additional call on the same grant, like
        `_invoke_with_backoff` retrying a 503 on the same cell.

        Does not take `self._lock`, same reasoning as `mark_rate_limited`."""

        async with session_scope() as session:
            await self.note_request_sent_with_session(session, key_index, model, now=now)

    async def note_request_sent_with_session(
        self, session: AsyncSession, key_index: int, model: str, *, now: datetime
    ) -> None:
        """Same as `note_request_sent`, reusing a caller-supplied session — for
        tests, same reasoning as `acquire_with_session`."""

        backend = _backend(key_index, model)
        reservation = await session.scalar(
            select(QuotaRequest)
            .where(QuotaRequest.backend == backend, QuotaRequest.confirmed.is_(False))
            .order_by(QuotaRequest.sent_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if reservation is None:
            session.add(QuotaRequest(backend=backend, sent_at=now, confirmed=True))
        else:
            reservation.sent_at = now
            reservation.confirmed = True
        await session.flush()

    async def _try_reserve_rpm(
        self, session: AsyncSession, key_index: int, rung: LadderRung, *, now: datetime
    ) -> bool:
        """Claim a place in this cell's trailing window, but only if the cell is
        under its ceiling. Returns False when it is already full.

        Checking and claiming are ONE statement on purpose. Split into a count
        followed by an insert, two processes both read "4 of 5 used", both
        insert, and the provider gets 6 -- exactly the cross-process gap this
        table exists to close. `INSERT ... SELECT ... WHERE (count) < rpm` is
        decided inside the database, so only one of them can win.
        """

        backend = _backend(key_index, rung.model)
        cutoff = now - timedelta(seconds=_RPM_WINDOW_SECONDS)
        in_window = (
            select(func.count())
            .select_from(QuotaRequest)
            .where(QuotaRequest.backend == backend, QuotaRequest.sent_at > cutoff)
            .scalar_subquery()
        )
        result = await session.execute(
            insert(QuotaRequest)
            .from_select(
                ["id", "backend", "sent_at", "confirmed"],
                select(
                    func.gen_random_uuid(),
                    literal(backend),
                    literal(now),
                    literal(False),
                ).where(in_window < rung.rpm),
            )
            .returning(QuotaRequest.id)
        )
        return result.scalar_one_or_none() is not None

    async def _earliest_send_in_window(
        self, session: AsyncSession, key_index: int, model: str, *, now: datetime
    ) -> datetime | None:
        """When the oldest request still inside this cell's window will fall out
        of it -- i.e. the soonest moment the cell could have room again."""

        cutoff = now - timedelta(seconds=_RPM_WINDOW_SECONDS)
        earliest: datetime | None = await session.scalar(
            select(func.min(QuotaRequest.sent_at)).where(
                QuotaRequest.backend == _backend(key_index, model),
                QuotaRequest.sent_at > cutoff,
            )
        )
        return earliest

    async def prune_request_window(self, session: AsyncSession, *, now: datetime) -> int:
        """Drop rows that have fallen out of every cell's window, refunding the
        day's ledger for any grant that never became a request (ADR-0061).

        These rows are worthless the moment they age out -- nothing reads this
        table for history -- so they are deleted rather than retained. Called
        opportunistically from `acquire()` rather than on a schedule, since the
        only process that needs the table small is one that is actively using
        it.

        **A row still `confirmed=False` this late is a phantom charge.**
        `acquire()` bills RPD when it GRANTS a cell, but the call fires later,
        after the caller wins `cell_lock` -- and `note_request_sent` is the first
        thing `_invoke_with_backoff` does, so all but a vanishing fraction of
        real sends are confirmed within milliseconds. A reservation still
        unconfirmed a full `_REQUEST_RETENTION_SECONDS` later therefore did not
        slip through the gap; it never happened at all -- the task died between
        the grant and the send (a cancelled `cell_lock` await, a client
        construction error, the process exiting mid-fan-out). Nothing else ever
        reconciles those, so they accumulate as permanent day-long loss.

        **Only never-sent grants are refunded, never rejected sends.** A request
        that reached the provider and came back 429 is confirmed, and stays
        billed even though the provider did not count it against its own daily
        total. That over-count is deliberate and load-bearing, not an oversight:
        `_invoke_with_retry`'s per-minute branch retries WITHOUT burning a cell,
        so the only thing that terminates it is the ledger climbing toward the
        cap. Refunding a throttled call would make that loop retry, refund, and
        retry forever -- and ADR-0060 widened the path into it by routing
        unidentifiable 429s there too. See ADR-0058's "Harder" note, which
        accepted this over-count knowingly.

        **A cell already marked exhausted is left alone**, so bookkeeping can
        never resurrect one that `mark_exhausted` deliberately retired for the
        day.
        """

        dropped = (
            await session.execute(
                delete(QuotaRequest)
                .where(QuotaRequest.sent_at < now - timedelta(seconds=_REQUEST_RETENTION_SECONDS))
                .returning(
                    QuotaRequest.backend, QuotaRequest.sent_at, QuotaRequest.confirmed
                )
            )
        ).all()

        # Keyed on the row's OWN day, not today's: retention outlives midnight,
        # so a run spanning it would otherwise refund yesterday's phantom
        # against today's fresh budget.
        phantoms: dict[tuple[datetime, str], int] = {}
        for backend, sent_at, confirmed in dropped:
            if confirmed:
                continue
            key = (_day_start(sent_at), backend)
            phantoms[key] = phantoms.get(key, 0) + 1

        for (day, backend), count in phantoms.items():
            ledger = await session.scalar(
                select(QuotaLedger).where(
                    QuotaLedger.day == day,
                    QuotaLedger.backend == backend,
                    QuotaLedger.exhausted_at.is_(None),
                )
            )
            if ledger is None:
                continue
            refunded = min(count, ledger.requests_spent)
            if refunded == 0:
                continue
            ledger.requests_spent -= refunded
            logger.info(
                "quota: refunded %d never-sent grant(s) to %s (now %d spent for %s)",
                refunded,
                backend,
                ledger.requests_spent,
                day.date(),
            )
        if phantoms:
            await session.flush()
        return len(dropped)

    async def _ledger_row(
        self, session: AsyncSession, day: datetime, key_index: int, model: str
    ) -> QuotaLedger:
        backend = _backend(key_index, model)
        row = await session.scalar(
            select(QuotaLedger).where(QuotaLedger.day == day, QuotaLedger.backend == backend)
        )
        if row is None:
            row = QuotaLedger(day=day, backend=backend, requests_spent=0)
            session.add(row)
            await session.flush()
        return row
