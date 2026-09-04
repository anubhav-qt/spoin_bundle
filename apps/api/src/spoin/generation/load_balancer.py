"""The per-box load balancer (ADR-0084) — one owner of a key subset, in memory.

Replaces the DB-backed `QuotaGovernor`. The generation pipeline is the only
process on the key pool (ADR-0082/0084), so the per-minute window, the learned
ceiling, and the model-unavailable set all live in memory here instead of in
`quota_request` / `model_unavailable`. Only the per-DAY count is still persisted
(`quota_ledger`, trimmed to `requests_spent`) — it has to survive the many
passes a day contains, or a resume re-spends budget.

Two scopes of balancer exist per run (see `GeminiContentGenerator`):

* one per **box**, over that topic's `topic_key_box_size` keys, built when the
  box is leased and dropped when it is released;
* one **remainder** balancer over the unboxed keys, for the claim-less calls
  (curriculum, topic matching, quiz grading, the recovery probe).

A balancer never shares a key with another balancer, so there is no
cross-balancer cell coordination — the `BoxPool` allocator hands out disjoint
index slices and keeps the remainder for itself.

Time is passed in as `now: datetime` on every method (as the old governor did)
so tests drive it by hand with no sleeps; internally it is reduced to
`now.timestamp()` float seconds for the window / cooldown / warm-up math.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import time
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from spoin.core.db import session_scope
from spoin.domain.models.quiz import QuotaLedger
from spoin.generation.quota import (
    AllModelsUnavailableError,
    DailyQuotaExhaustedError,
    LadderRung,
    _day_start,
)

logger = logging.getLogger("spoin.generation.load_balancer")

#: The trailing window RPM is measured over — 60s is what "per minute" means.
_WINDOW_S = 60.0
#: Upper bound on the per-minute cooldown when a 429 arrives with no `RetryInfo`.
#: One full window is the longest a per-minute limit can last. It is a CAP, not
#: the wait itself -- `on_rate_limited` prefers the cell's own window, which is
#: the same fact measured instead of assumed.
_COOLDOWN_S = 60.0
#: A fresh balancer treats every cell as cooling for this long (ADR-0084 §4):
#: its in-memory window starts empty but its keys may have been hot seconds ago
#: (a crash-restart mid-box), and a box's first pass must not co-burst with the
#: previous one on an empty belief.
_WARMUP_S = 60.0
#: The slowest a cell's learned rpm can get. One request per minute is the last
#: pace that is still a pace; below it the cell is switched off and can never
#: produce the clean call that would let it speed back up.
_RPM_FLOOR = 1.0
#: Write the day's count back to `quota_ledger` once a cell has spent this many
#: unflushed requests (plus always on release). Bounds ledger writes to ~1 per
#: 10 calls per cell while keeping a crash-resume accurate to within this many.
_FLUSH_EVERY = 10

#: `(key_index, model)`.
Cell = tuple[int, str]
#: What kind of work a call is — picks which ladder the balancer walks.
LadderKind = str  # "generator" | "thinking"

#: The balancer in force for the current task — a box's, set by
#: `claimed_key_scope`, or `None` outside any boxed scope (the claim-less path
#: falls back to the remainder balancer). A `ContextVar` for the same reason the
#: old `CURRENT_KEY_CLAIM` was: which keys a call may use is a quota concern and
#: has no business as a parameter on the content interface. asyncio copies the
#: context into every task, so a scope set at a LangGraph branch is inherited by
#: every call that branch fans out.
CURRENT_BALANCER: ContextVar[LoadBalancer | None] = ContextVar(
    "spoin_current_balancer", default=None
)

#: Best-effort write-through: `(key_index, model, requests_spent) -> None`.
LedgerWriter = Callable[[int, str, int], Awaitable[None]]


def estimate_tokens(text: str) -> int:
    """A prompt's token cost, before it is sent (ADR-0085).

    Four characters per token is the usual English rule of thumb. It is an
    ESTIMATE and deliberately so: the exact count is only knowable from the
    response's `usageMetadata`, which `with_structured_output` does not surface
    (it returns the parsed model, not the `AIMessage`) -- reconciling against the
    real figure is deferred, see docs/tasks. The window this feeds is a brake,
    and a brake sized on a ~20% estimate still brakes.
    """

    return max(1, len(text) // 4)


def pack_by_tokens[T](
    items: Sequence[T], *, cost: Callable[[T], int], budget: int, max_items: int
) -> list[list[T]]:
    """Chunk `items` so each chunk's estimated prompt cost stays under `budget`,
    and no chunk holds more than `max_items` (ADR-0085).

    This is the "spillover" half of token metering: the batch-size setting stays
    the CEILING on how many items a call may carry, and the token budget cuts it
    shorter whenever the items are fat. What does not fit becomes the next
    chunk, and because every chunk is its own request it gets its own
    `(key, model)` from `assign()` -- so an overlong batch spreads across cells
    instead of overrunning one cell's minute.

    An item that is over budget on its own still gets a chunk to itself:
    splitting one card's body is not this function's business, and dropping it
    would be a silent loss of content to satisfy an estimate.
    """

    chunks: list[list[T]] = []
    current: list[T] = []
    spent = 0
    for item in items:
        item_cost = cost(item)
        if current and (len(current) >= max_items or spent + item_cost > budget):
            chunks.append(current)
            current = []
            spent = 0
        current.append(item)
        spent += item_cost
    if current:
        chunks.append(current)
    return chunks


def _backend(key_index: int, model: str) -> str:
    """The `(key, model)` cell's spelling in `quota_ledger.backend`."""

    return f"gemini:{key_index}:{model}"


async def seed_rpd(
    key_indices: tuple[int, ...], models: frozenset[str], *, now: datetime
) -> dict[Cell, int]:
    """Read today's `requests_spent` for the given cells from `quota_ledger`,
    ONCE, at balancer construction (ADR-0084 §1). Everything after is the
    in-memory counter; the ledger is only touched again by the write-through."""

    day = _day_start(now)
    wanted = {_backend(k, m) for k in key_indices for m in models}
    async with session_scope() as session:
        rows = await session.execute(
            select(QuotaLedger.backend, QuotaLedger.requests_spent).where(QuotaLedger.day == day)
        )
    seed: dict[Cell, int] = {}
    for backend, spent in rows.all():
        if backend not in wanted:
            continue
        parts = backend.split(":", 2)
        seed[(int(parts[1]), parts[2])] = spent
    return seed


def make_ledger_writer() -> LedgerWriter:
    """A write-through that upserts one cell's day count. Best-effort and off
    the hot path — a lost write costs at most `_FLUSH_EVERY` of resume accuracy,
    never correctness within a run."""

    async def _write(key_index: int, model: str, requests_spent: int) -> None:
        async with session_scope() as session:
            await session.execute(
                pg_insert(QuotaLedger)
                .values(
                    day=_day_start(datetime.now(UTC)),
                    backend=_backend(key_index, model),
                    requests_spent=requests_spent,
                )
                .on_conflict_do_update(
                    index_elements=["day", "backend"],
                    set_={"requests_spent": requests_spent, "updated_at": func.now()},
                )
            )

    return _write


@dataclass
class _Slot:
    """One reserved place in a cell's trailing window. Held by reference in the
    `Reservation` handed back to the caller, so `note_send` / `on_send_aborted`
    move or drop *this* request's timestamp even when another call has reserved
    the same cell in between."""

    sent_at: float


@dataclass
class Reservation:
    """What `assign()` returns: the cell to call, plus a private handle to the
    window slot it took. Pass it straight back to `on_success` /
    `on_rate_limited` / `note_send` / `on_send_aborted`."""

    key_index: int
    model: str
    _slot: _Slot = field(repr=False)
    #: Epoch seconds when `assign()` chose this cell. The send happens later --
    #: after the caller acquires `cell_lock` -- and the difference is the
    #: instrumentation in `note_send` (probe A): a reservation that waits a long
    #: time behind the lock is one the send gap spaced in name only.
    reserved_at: float = 0.0


@dataclass
class _CellState:
    rpd_limit: int
    configured_rpm: int
    tpm_limit: int
    rpd_spent: int
    day: datetime
    #: epoch seconds of this cell's last dispatch/send. The per-(key, model)
    #: send gap (ADR-0084) is measured from here -- see `LoadBalancer._gap_for`,
    #: which is also why the trailing window below is dormant under pacing.
    last_send: float = 0.0
    #: How many times THIS balancer has dispatched to this cell. The primary
    #: sort key in `try_assign` -- strict round-robin so every (key, model) pair
    #: carries an even share, not just whichever had the coldest ledger seed.
    dispatched: int = 0
    window: deque[_Slot] = field(default_factory=deque)
    #: `(sent_at, tokens)` for each send inside the trailing minute -- the token
    #: analogue of `window`, pruned on the same 60s cutoff (ADR-0085). Unlike
    #: the request window this is NOT dormant under pacing: a constant send gap
    #: bounds requests per minute, and says nothing at all about tokens.
    token_window: deque[tuple[float, int]] = field(default_factory=deque)
    learned_rpm: float = 0.0
    cooldown_until: float = 0.0
    last_probe_up: float = 0.0
    flushed_at: int = 0

    def __post_init__(self) -> None:
        if self.learned_rpm == 0.0:
            self.learned_rpm = float(self.configured_rpm)
        self.flushed_at = self.rpd_spent

    def prune(self, now_s: float) -> None:
        cutoff = now_s - _WINDOW_S
        while self.window and self.window[0].sent_at <= cutoff:
            self.window.popleft()
        while self.token_window and self.token_window[0][0] <= cutoff:
            self.token_window.popleft()

    @property
    def windowed_tokens(self) -> int:
        """Tokens sent to this cell inside the trailing minute. Call `prune`
        first -- this does not prune, so it stays cheap in the assign loop."""

        return sum(t for _, t in self.token_window)

    def roll_day(self, now: datetime) -> None:
        start = _day_start(now)
        if start == self.day:
            return
        # A new day genuinely starts at zero. The ledger seed we were built with
        # is yesterday's; nothing to carry.
        self.rpd_spent = 0
        self.flushed_at = 0
        self.learned_rpm = float(self.configured_rpm)
        self.window.clear()
        self.token_window.clear()
        self.cooldown_until = 0.0
        self.day = start

    @property
    def ceiling(self) -> int:
        return max(1, int(self.learned_rpm))


class LoadBalancer:
    """Owns a fixed set of keys and both model ladders for one box (or the
    remainder). `assign(kind)` picks the strongest ladder rung with a key that
    has day budget, is not cooling, and has room in its trailing minute —
    least-spent key first (ADR-0065 / ADR-0083, now a pure in-memory sort).
    """

    def __init__(
        self,
        *,
        name: str,
        key_indices: tuple[int, ...],
        generator_ladder: list[LadderRung],
        thinking_ladder: list[LadderRung],
        model_unavailable: dict[str, float],
        rpd_seed: dict[Cell, int],
        now: datetime,
        ledger_writer: LedgerWriter | None = None,
        send_gap_s: float = 0.0,
        dispatch_stagger_s: float = 0.0,
        active_key_window: int = 0,
    ) -> None:
        if not key_indices:
            raise ValueError("LoadBalancer needs at least one key")
        self.name = name
        self.key_indices = tuple(key_indices)
        #: Only these keys are dispatchable right now -- a sliding window over the
        #: box (`settings.gemini_active_key_window`). Google throttles on the
        #: source IP, and spreading one IP's traffic across 100+ distinct keys
        #: measurably degrades it (42.2% failure and climbing on 108 keys vs 18.9%
        #: flat on 20, at identical request rate -- see the config comment). 0
        #: disables windowing and every key stays live, which is what tests and
        #: the `fake` backend want.
        #:
        #: Rotation is driven ONLY by facts local to the window -- its top rung
        #: being spent, or the whole window being out of budget. It is explicitly
        #: NOT driven by the failure rate. A rate-triggered version shipped and was
        #: measured on 2026-09-04: it rotated 14 times in 4 minutes on spikes of
        #: 60-100%, because every window it moved to spiked too. Throttling here is
        #: keyed to the source IP, so a high failure rate is a GLOBAL fact that
        #: rotating cannot escape -- and chasing it cycled the full 108-key box
        #: every ~2 minutes, recreating the exact many-keys regime (42% failure and
        #: climbing) that holding at 25 keys (18.9%, flat) exists to avoid.
        self._window_size = active_key_window if 0 < active_key_window < len(key_indices) else 0
        self._window_start = 0
        self._active_keys = self._window_of(0)
        self._ladders: dict[LadderKind, list[LadderRung]] = {
            "generator": generator_ladder,
            "thinking": thinking_ladder,
        }
        #: model -> epoch expiry, SHARED BY REFERENCE across every balancer in
        #: the run: a 503/504 is a property of the model at the provider, not of
        #: one box's keys.
        self._model_unavailable = model_unavailable
        self._ledger_writer = ledger_writer
        #: Minimum seconds between two sends to the SAME `(key, model)` cell
        #: (`settings.gemini_send_gap_seconds`) -- a FLOOR, widened per rung by
        #: `_gap_for`. This is the burst brake AND the whole rate limiter: with it on, the
        #: trailing-60s window and the learned-rpm ceiling are dormant (a
        #: constant gap already caps the rate and evens the spread). 0 re-enables
        #: the window (`fake`, tests, and any experiment that sets the gap to 0).
        self._send_gap_s = send_gap_s
        self._paced = send_gap_s > 0.0
        #: Minimum seconds between ANY two dispatches across this entire balancer
        #: (`settings.gemini_dispatch_stagger_seconds`, ADR-0086). While `_send_gap_s`
        #: spaces sends to the SAME cell, this paces dispatches across DIFFERENT cells
        #: to prevent simultaneous edge-gateway shedding on parallel fanout.
        self._dispatch_stagger_s = dispatch_stagger_s
        self._last_pool_send: float = 0.0
        self._lock = asyncio.Lock()
        self._cell_locks: dict[Cell, asyncio.Lock] = {}
        self._created_s = now.timestamp()

        self._cells: dict[Cell, _CellState] = {}
        day = _day_start(now)
        for rungs in self._ladders.values():
            for rung in rungs:
                for k in self.key_indices:
                    cell = (k, rung.model)
                    seed = rpd_seed.get(cell, 0)
                    existing = self._cells.get(cell)
                    if existing is not None:
                        existing.rpd_spent = max(existing.rpd_spent, seed)
                        continue
                    self._cells[cell] = _CellState(
                        rpd_limit=rung.rpd,
                        configured_rpm=rung.rpm,
                        tpm_limit=rung.tpm,
                        rpd_spent=seed,
                        day=day,
                    )

    # -- introspection ------------------------------------------------------

    @property
    def key_count(self) -> int:
        return len(self.key_indices)

    # -- active key window --------------------------------------------------

    def _window_of(self, start: int) -> tuple[int, ...]:
        """The `_window_size` keys beginning at `start`, wrapping the box."""

        if not self._window_size:
            return self.key_indices
        n = len(self.key_indices)
        return tuple(self.key_indices[(start + i) % n] for i in range(self._window_size))

    def _rotate_window(self, reason: str) -> None:
        """Move to the next slice of the box."""

        if not self._window_size:
            return
        self._window_start = (self._window_start + self._window_size) % len(self.key_indices)
        self._active_keys = self._window_of(self._window_start)
        logger.info(
            "lb %s: rotating active key window -> %d key(s) starting at %d (%s)",
            self.name,
            len(self._active_keys),
            self._active_keys[0],
            reason,
        )

    def _top_rung_spent(self, kind: LadderKind, now_s: float) -> bool:
        """True when no ACTIVE key has daily budget left on the ladder's strongest
        still-available rung.

        Degrading to a weaker model is worse than moving to fresh keys that still
        have the strong one, so this is a rotation trigger. Rungs the provider has
        marked unavailable (503/504) are skipped rather than counted as spent --
        that is an outage, and rotating keys cannot fix it.
        """

        if not self._window_size:
            return False
        for rung in self._ladders[kind]:
            if self._model_unavailable.get(rung.model, 0.0) > now_s:
                continue
            return all(
                self._cells[(k, rung.model)].rpd_spent >= self._cells[(k, rung.model)].rpd_limit
                for k in self._active_keys
            )
        return False

    def _rotate_to_any_budget(self, kind: LadderKind, now_s: float) -> bool:
        """Walk the remaining windows for one with ANY budget on any rung.

        Distinguishes "this window is spent" (rotate, keep going) from "the whole
        box is spent" (the caller's `DailyQuotaExhaustedError` is real).
        """

        if not self._window_size:
            return False
        n = len(self.key_indices)
        starts = range(self._window_size, n, self._window_size)
        for step in starts:
            start = (self._window_start + step) % n
            candidate = self._window_of(start)
            for rung in self._ladders[kind]:
                if self._model_unavailable.get(rung.model, 0.0) > now_s:
                    continue
                if any(
                    self._cells[(k, rung.model)].rpd_spent < self._cells[(k, rung.model)].rpd_limit
                    for k in candidate
                ):
                    self._window_start = start
                    self._active_keys = candidate
                    logger.info(
                        "lb %s: active window spent -- rotating to %d key(s) starting at %d",
                        self.name,
                        len(candidate),
                        candidate[0],
                    )
                    return True
        return False

    def ladder(self, kind: LadderKind) -> list[LadderRung]:
        return self._ladders[kind]

    def cell_lock(self, key_index: int, model: str) -> asyncio.Lock:
        """The lock a caller holds around the actual network call (ADR-0040) —
        NOT around `assign()`. Same-cell calls queue; different cells stay
        concurrent."""

        cell = (key_index, model)
        lock = self._cell_locks.get(cell)
        if lock is None:
            lock = asyncio.Lock()
            self._cell_locks[cell] = lock
        return lock

    def _gap_for(self, cell: _CellState) -> float:
        """The send gap THIS cell must honour: the configured gap, but never
        faster than the cell's own rung allows.

        `gemini_send_gap_seconds` is one constant, and the two ladders are not
        one rate -- the thinking rungs are rpm 5 (a 12s gap) and the generator
        rungs rpm 15 (4s). Applying the configured gap to both drove every
        thinking cell 3x over its documented limit at the 4s setting. The
        configured value stays a floor so an experiment can still slow the whole
        pool down; it can no longer speed a rung past its own ceiling.
        """

        return max(self._send_gap_s, _WINDOW_S / max(1, cell.configured_rpm))

    # -- assignment -------------------------------------------------------

    async def assign(
        self,
        kind: LadderKind,
        *,
        now: datetime,
        est_tokens: int = 0,
        exclude_models: frozenset[str] = frozenset(),
    ) -> Reservation:
        """A cell to make the next `kind` call on. Sleeps and retries while the
        only thing wrong is a cooldown or a full minute; raises the matching
        `QuotaExhaustedError` subclass when nothing will serve soon."""

        while True:
            outcome = await self.try_assign(
                kind, now=now, est_tokens=est_tokens, exclude_models=exclude_models
            )
            if isinstance(outcome, Reservation):
                return outcome
            wait_s = outcome
            logger.info("lb %s: no %s cell right now -- waiting %.1fs", self.name, kind, wait_s)
            started = time.monotonic()
            await asyncio.sleep(wait_s)
            # Advance by the time that ACTUALLY passed. `asyncio.sleep(w)` returns
            # no earlier than `w` but, on a loaded event loop, often much later --
            # and this loop can run thousands of times in a starved pass. Adding
            # the nominal `w` let this clock drift behind the real one, and the
            # stamp a reservation then writes to `cell.last_send` under-states how
            # recently the cell was used, which un-blocks the send gap early and
            # lets a burst through on a cell whose AVERAGE rate still looks calm.
            now = now + timedelta(seconds=max(wait_s, time.monotonic() - started))

    async def try_assign(
        self,
        kind: LadderKind,
        *,
        now: datetime,
        est_tokens: int = 0,
        exclude_models: frozenset[str] = frozenset(),
    ) -> Reservation | float:
        """One pass, no sleeping: a `Reservation`, or the seconds to wait before
        asking again. Raises `DailyQuotaExhaustedError` / `AllModelsUnavailableError`
        when the wait would never end."""

        now_s = now.timestamp()
        warm_until = self._created_s + _WARMUP_S
        async with self._lock:
            # Pool-wide dispatch staggering (ADR-0086): don't dispatch again until
            # dispatch_stagger_s has elapsed since the last reservation across ANY cell
            # in this balancer.
            if self._dispatch_stagger_s > 0.0 and self._last_pool_send > 0.0:
                stagger_left = self._dispatch_stagger_s - (now_s - self._last_pool_send)
                if stagger_left > 0.0:
                    return stagger_left

            # Strongest rung dry across the window? Move to fresh keys rather
            # than serve this call on a weaker model.
            if self._top_rung_spent(kind, now_s):
                self._rotate_window("top rung exhausted across the active window")

            any_model_checked = False
            any_budget = False
            soonest = math.inf
            best: tuple[Cell, _CellState, tuple[int, int, int]] | None = None

            for rung in self._ladders[kind]:
                if rung.model in exclude_models:
                    continue
                if self._model_unavailable.get(rung.model, 0.0) > now_s:
                    continue
                any_model_checked = True
                for k in self._active_keys:
                    cell_id = (k, rung.model)
                    cell = self._cells[cell_id]
                    cell.roll_day(now)
                    cell.prune(now_s)
                    if cell.rpd_spent >= cell.rpd_limit:
                        continue
                    any_budget = True
                    block_until = max(cell.cooldown_until, warm_until)
                    if block_until > now_s:
                        soonest = min(soonest, block_until - now_s)
                        continue
                    # Per-(key, model) send gap (ADR-0084): don't hit this exact
                    # cell again until this cell's own gap has passed -- see
                    # `_gap_for`. It IS the rate limiter when pacing is on.
                    if self._send_gap_s > 0.0:
                        gap_left = self._gap_for(cell) - (now_s - cell.last_send)
                        if gap_left > 0.0:
                            soonest = min(soonest, gap_left)
                            continue
                    # Trailing-minute TOKEN ceiling (ADR-0085). Unlike the
                    # request window this always gates: the send gap bounds
                    # requests per minute and says nothing about tokens, and a
                    # batch call's token cost varies by orders of magnitude.
                    if est_tokens and cell.windowed_tokens + est_tokens > cell.tpm_limit:
                        # Wait for the oldest tokens to age out of the minute.
                        if cell.token_window:
                            soonest = min(soonest, cell.token_window[0][0] + _WINDOW_S - now_s)
                        continue
                    # The trailing-60s window only gates when pacing is OFF --
                    # a constant per-cell gap already caps the rate (see
                    # `_paced`).
                    if not self._paced and len(cell.window) >= cell.ceiling:
                        soonest = min(soonest, cell.window[0].sent_at + _WINDOW_S - now_s)
                        continue
                    # Round-robin: fewest dispatches this run first, then the
                    # coldest ledger seed, then key index.
                    score = (cell.dispatched, cell.rpd_spent, k)
                    if best is None or score < best[2]:
                        best = (cell_id, cell, score)
                # Model-major (ADR-0028): take the best key on the strongest rung
                # that has one; only fall to a weaker model when this one has
                # nothing.
                if best is not None:
                    break

            if best is not None:
                cell_id, cell, _ = best
                slot = _Slot(sent_at=now_s)
                cell.window.append(slot)
                cell.last_send = max(cell.last_send, now_s)
                self._last_pool_send = max(self._last_pool_send, now_s)
                cell.dispatched += 1
                return Reservation(
                    key_index=cell_id[0],
                    model=cell_id[1],
                    _slot=slot,
                    reserved_at=now_s,
                )

            if not any_model_checked:
                raise AllModelsUnavailableError(
                    f"lb {self.name}: every {kind} rung is excluded as unavailable "
                    f"-- provider outage, not quota"
                )
            if not any_budget:
                # Only the ACTIVE WINDOW is dry. That is not the same fact as the
                # box being spent, and reporting it as one would end a run with
                # 80+ untouched keys sitting in the box.
                if self._rotate_to_any_budget(kind, now_s):
                    return 0.5
                raise DailyQuotaExhaustedError(
                    f"lb {self.name}: all {self.key_count} key(s) exhausted on every "
                    f"{kind} rung for {_day_start(now).date()}"
                )
            wait = soonest if soonest != math.inf else 2.0
            return max(0.5, min(wait + 0.2, 60.0))

    # -- feedback from the call --------------------------------------------

    def note_send(self, res: Reservation, *, now: datetime, tokens: int = 0) -> None:
        """The request is leaving now — move its window slot to the true send
        time (ADR-0058's alignment fix) and re-anchor the per-cell send gap to
        it, so a call delayed behind `cell_lock` still spaces the next one out
        by the full gap."""

        cell = self._cells[(res.key_index, res.model)]
        now_s = now.timestamp()
        # PROBE A (temporary, 2026-09-03): what the provider actually sees.
        # `since_last` is the real spacing between two sends to this cell --
        # the send gap is enforced at RESERVATION time, so a call that waited
        # behind `cell_lock` can land far closer to its predecessor than the
        # gap believes. `queued` is how long this reservation sat before
        # sending; queue depth is roughly `queued / gap`.
        logger.info(
            "lbprobe send key=%d model=%s since_last=%.2f queued=%.2f gap=%.2f",
            res.key_index,
            res.model,
            now_s - cell.last_send,
            now_s - res.reserved_at if res.reserved_at else 0.0,
            self._gap_for(cell),
        )
        res._slot.sent_at = now_s
        cell.last_send = max(cell.last_send, now_s)
        self._last_pool_send = max(self._last_pool_send, now_s)
        if tokens:
            # Anchored to the true send time for the same reason the request
            # slot is (ADR-0058): a call delayed behind `cell_lock` spends its
            # tokens in the minute it actually leaves, not the one it reserved.
            cell.token_window.append((now_s, tokens))

    async def on_success(self, res: Reservation, *, now: datetime) -> None:
        cell = self._cells[(res.key_index, res.model)]
        cell.rpd_spent += 1
        now_s = now.timestamp()
        # Learned-rpm probe (dormant under pacing — the constant gap is the
        # ceiling). Only when the window is the limiter: +1 per clean minute,
        # capped at the configured rpm.
        if (
            not self._paced
            and cell.learned_rpm < cell.configured_rpm
            and now_s - cell.last_probe_up >= _WINDOW_S
        ):
            cell.learned_rpm = min(float(cell.configured_rpm), cell.learned_rpm + 1.0)
            cell.last_probe_up = now_s
        await self._maybe_flush(res.key_index, res.model, cell)

    def on_rate_limited(
        self,
        res: Reservation,
        *,
        now: datetime,
        per_minute: bool,
        retry_after_s: float | None = None,
    ) -> None:
        """A 429. Per-minute: park the cell for the cooldown. When pacing is OFF
        the cell also learns its real ceiling from the sends that were in the
        window when it refused (a measured cap, not AIMD's blind halving); when
        pacing is ON the constant gap is the only knob and the learned rpm stays
        put. Per-day: the cell is spent until the daily reset."""

        cell = self._cells[(res.key_index, res.model)]
        now_s = now.timestamp()
        if per_minute:
            cell.prune(now_s)
            if retry_after_s:
                cell.cooldown_until = now_s + retry_after_s
            else:
                # No `RetryInfo`. The earliest this cell can be back inside its
                # per-minute allowance is one full window after its OLDEST still-
                # live send -- not a flat minute from now, which re-serves time
                # the window has already served. `_COOLDOWN_S` stays the bound
                # for a cell with nothing left in its window to reason from.
                oldest = cell.window[0].sent_at if cell.window else now_s
                cell.cooldown_until = min(now_s + _COOLDOWN_S, oldest + _WINDOW_S)
            if self._paced:
                return
            measured = max(1, len(cell.window))  # the refused call WAS sent — keep its slot
            if measured < cell.learned_rpm:
                logger.info(
                    "lb %s: key %d model %s throttled -- learned rpm %.1f -> %d (configured %d)",
                    self.name,
                    res.key_index,
                    res.model,
                    cell.learned_rpm,
                    measured,
                    cell.configured_rpm,
                )
            cell.learned_rpm = max(_RPM_FLOOR, min(cell.learned_rpm, float(measured)))
        else:
            cell.rpd_spent = cell.rpd_limit
            logger.warning(
                "lb %s: key %d model %s got a per-day 429 despite our count showing room "
                "-- marking spent for the day",
                self.name,
                res.key_index,
                res.model,
            )

    def on_send_aborted(self, res: Reservation) -> None:
        """The call raised before the request left (a timeout, a transport
        error). Drop its window slot — it never counted against the provider
        (ADR-0061's refund, now a `deque.remove`)."""

        cell = self._cells.get((res.key_index, res.model))
        if cell is None:
            return
        with contextlib.suppress(ValueError):
            cell.window.remove(res._slot)
        # Refund the token slot too -- an aborted send spent no tokens either.
        for i in range(len(cell.token_window) - 1, -1, -1):
            if cell.token_window[i][0] == res._slot.sent_at:
                del cell.token_window[i]
                break

    def mark_exhausted(self, key_index: int, model: str) -> None:
        """Force a cell spent for the day — an auth failure (401/403), or a
        model a recovery probe never got an answer from."""

        cell = self._cells.get((key_index, model))
        if cell is not None:
            cell.rpd_spent = cell.rpd_limit

    def exclude_model(self, model: str, *, now: datetime, expires_in_s: float) -> None:
        """Park a model out of rotation for every balancer in the run."""

        self._model_unavailable[model] = now.timestamp() + expires_in_s

    def include_model(self, model: str) -> None:
        self._model_unavailable.pop(model, None)

    # -- persistence ----------------------------------------------------

    async def _maybe_flush(self, key_index: int, model: str, cell: _CellState) -> None:
        if self._ledger_writer is None:
            return
        if cell.rpd_spent - cell.flushed_at < _FLUSH_EVERY:
            return
        cell.flushed_at = cell.rpd_spent
        await self._ledger_writer(key_index, model, cell.rpd_spent)

    async def flush(self) -> None:
        """Write every cell's day count back to the ledger — called on release
        so a resume picks up an accurate seed."""

        if self._ledger_writer is None:
            return
        for (key_index, model), cell in self._cells.items():
            if cell.rpd_spent != cell.flushed_at:
                cell.flushed_at = cell.rpd_spent
                await self._ledger_writer(key_index, model, cell.rpd_spent)
