"""The quota governor (ADR-0003 §6, redesigned per ADR-0028) — a key x model
grid, not a flat list of keys.

Gemini rate limits are per-project, not per-key (ADR-0028's finding) — so each
entry in `SPOIN_GEMINI_API_KEYS` is assumed to be its own project, and each
model in a ladder has its OWN daily/per-minute limit, independent of every
other model. `QuotaGovernor` walks that grid: for a call, try the strongest
model in the ladder across every configured key; only fall to the next model
once every key is exhausted for the current one.

**Within a rung, keys are tried least-spent first** (ADR-0065), not in index
order. First-fit from key 0 is what made a 33-key pool behave like a 9-key one:
the lowest free key wins every grant, so it climbs toward its ceiling while the
rest of the grid sits at whatever a single early burst left them at.

**The configured `rpm` is a starting belief, not a fact** (ADR-0065). Each cell
carries a learned effective rpm that halves on a per-minute 429 and grows back
on success, so the governor converges on the provider's real ceiling instead of
arguing with it 429 at a time.

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
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, insert, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from spoin.core.db import session_scope
from spoin.domain.models.quiz import ModelUnavailable, QuotaLedger, QuotaRequest

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
#: The slowest a cell's learned rpm can get (ADR-0065). One request per minute
#: is the last pace that is still a pace -- below it the cell isn't throttled,
#: it's switched off, and a cell we have stopped sending to can never produce
#: the evidence that would let us speed it back up.
_EFFECTIVE_RPM_FLOOR = 1.0


def _backend(key_index: int, model: str) -> str:
    """The `(key, model)` cell's key in both quota tables. One spelling, one
    place -- `QuotaLedger` and `QuotaRequest` describe the same cell on two
    different time horizons and must agree on how it is named."""

    return f"gemini:{key_index}:{model}"


class QuotaExhaustedError(RuntimeError):
    """`acquire()` could not grant a cell and will not be able to soon.

    ADR-0003 §6: this is a real, expected outcome to degrade gracefully from —
    not a try/except accident. The worker (`apps/worker/__main__.py`) catches
    this specifically and requeues the job as `pending` rather than `failed`,
    since `run_generation_pipeline` is idempotent (ADR-0026) and safely
    resumes once quota resets.

    **Never raised directly — always one of the three subclasses below**
    (ADR-0065). This class used to BE the outcome, with one message asserting
    "all N keys x M models exhausted" regardless of which of three unrelated
    conditions actually stopped the run. That is the same failure/rejection
    conflation CLAUDE.md warns about, one level down: a provider outage and a
    genuinely spent daily budget are different facts about the world, they call
    for different responses, and folding them together made a 504 storm get
    reported as quota death while ~90% of the grid sat untouched. Callers that
    genuinely don't care (the worker's requeue path) still catch this base.
    """


class DailyQuotaExhaustedError(QuotaExhaustedError):
    """Every `(key, model)` cell has spent its RPD. The real thing: nothing
    more can be sent today, and the only cure is the daily reset."""


class AllCellsThrottledError(QuotaExhaustedError):
    """Every cell with daily quota left is in a per-minute cooldown, and has
    been for long enough that waiting is no longer distinguishable from being
    stuck (see `_invoke_with_retry`'s throttle streak).

    Transient by definition -- daily budget remains. A caller that treats this
    like `DailyQuotaExhaustedError` and stands down until midnight is throwing
    away quota it still has."""


class AllModelsUnavailableError(QuotaExhaustedError):
    """Every rung in the ladder is excluded as unavailable (a 503 overload or a
    504 stall), so there is no model left to route to.

    Says nothing about quota -- the ledger may be nearly untouched. This is a
    provider outage surfacing as a local dead end, and it resolves when the
    provider does, not when the day rolls over."""


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


async def key_spend_today(
    session: AsyncSession, *, key_count: int, now: datetime
) -> dict[int, int]:
    """`key_index -> total requests spent today` across EVERY cell of that key
    (both pools' ladders write into the same `QuotaLedger`). Used to fill a key
    box coldest-first (ADR-0082) so per-day usage doesn't pile onto low-index
    keys pass after pass -- the same skew ADR-0065 removed from the per-call
    scan, which a box held for a whole run would otherwise reintroduce. A key
    with no rows is absent, which reads as 0 -- an untouched key is the coldest
    there is."""

    rows = await session.execute(
        select(QuotaLedger.backend, QuotaLedger.requests_spent).where(
            QuotaLedger.day == _day_start(now)
        )
    )
    totals: dict[int, int] = {}
    for backend, spent in rows.all():
        # backend is "gemini:{key_index}:{model}"
        parts = backend.split(":")
        if len(parts) < 3 or not parts[1].isdigit():
            continue
        key_index = int(parts[1])
        if 0 <= key_index < key_count:
            totals[key_index] = totals.get(key_index, 0) + spent
    return totals


@dataclass
class KeyBox:
    """One TOPIC's entire key pool for the whole of its generation run
    (ADR-0082).

    A box is a fixed-size slice of the pool -- `settings.topic_key_box_size`
    keys -- handed to a topic when its run starts and returned when it ends.
    Inside the box, ADR-0074 is unchanged: a subtopic group claims one key for
    its whole card run, and a group whose key is spent moves to another key IN
    THIS BOX. Outside it, nothing: a box is the topic's total pool, not a
    preference. That is what makes the hybrid bound sayable in one line --
    `pool / box_size` topics at once, ADR-0074 within each.

    Deliberately NOT a lease with a shared reserve to fall back on
    ([ADR-0078](../../../../docs/adr/0078-topic-parallel-key-leases.md), which
    was reverted): a fallback that reaches outside the box makes the number of
    callers on a key a function of how spent the other boxes are, and that is
    exactly the unbounded per-minute pressure the revert was for.
    """

    #: Stable id for log lines -- a box is otherwise identified only by which
    #: keys it holds.
    box_id: int
    key_indices: set[int] = field(default_factory=set)


@dataclass
class KeyClaim:
    """One unit of work's ownership of an API key (ADR-0074).

    `key_index` starts unbound: the first `acquire()` made under this claim
    binds it to whichever free key is least spent, so the choice uses the same
    ledger query that orders keys everywhere else rather than a second, weaker
    notion of "least used" kept in memory. It can move -- step 3 of the ADR's
    ladder re-claims a different key when the held one has no room on any
    preferred rung -- which is why this is a mutable handle and not just an int.

    `box` (ADR-0082) is the set of keys that "another key" may mean: with a box
    set, every scan this claim makes -- the first bind, the move to a fresher
    key, the "is the day gone?" check -- sees only the box's keys, so a topic
    can never reach into another topic's. `None` keeps ADR-0074's whole-pool
    behaviour, which is the lease-less path (the API's topic matching, the
    recovery probe, the `fake` backend, and every test that doesn't box).

    `sticky` False turns the pin off: the claim still narrows every scan to its
    `box`, but a grant never `bind`s, so `key_index` stays None and the NEXT
    call re-picks the least-spent key in the box from scratch. ADR-0074's pin
    forced a unit's whole burst of calls -- a tier's plan + one draft per card
    type + ascii fetch/redraw, ~10 in a few seconds -- onto ONE key, tripping
    its 15-rpm ceiling while the unit's average rate stayed tiny; spreading
    that burst least-spent-first across the box is the pre-ADR-0074 ADR-0065
    behaviour, kept inside the box. `cell_lock` + `_try_reserve_rpm`'s atomic
    reservation still guarantee one caller per CELL, which is what actually
    made an rpm violation impossible -- the pin was a concurrency heuristic on
    top of that, and the heuristic is what unbalanced the load. Card writing,
    planning, ascii and question generation pass `sticky=False`; the thinking
    gate goes further and drops the claim entirely (pool-wide).
    """

    key_index: int | None = None
    box: KeyBox | None = None
    sticky: bool = True


class KeyClaimRegistry:
    """Which keys are currently owned, shared by BOTH pools of one generator.

    A KEY is the unit of ownership, not a `(key, model)` cell: the thinking and
    generator pools are separate `QuotaGovernor`s over the same physical keys,
    so a claim invisible to the other pool would let one group's card writing
    contend with another group's judging on the same project -- exactly the
    concurrency ADR-0074 exists to remove.

    The registry also owns KEY BOXES (ADR-0082) -- fixed-size slices of the pool
    held by one topic for its whole run. Boxes and claims are the same two-level
    story from opposite ends: a box says which keys a topic may use, a claim says
    which single key a subtopic group inside it is using right now. They live
    together here because both answer "who owns key N", and splitting them would
    let a box hand out a key a claim still holds.

    In-process only, deliberately. Boxes and claims bound concurrency *within*
    one worker process -- the several jobs a pass runs concurrently share one
    generator, hence one registry; the cross-process story stays what it has
    always been -- `_try_reserve_rpm`'s atomic reservation and the shared ledger
    (ADR-0058). A DB-backed claim would add a lock nothing currently needs and a
    crash-recovery problem (a claim outliving the process that took it) for a
    case that does not arise.
    """

    def __init__(self, key_count: int) -> None:
        if key_count < 1:
            raise ValueError("KeyClaimRegistry needs at least one key")
        self._key_count = key_count
        self._claimed: dict[int, KeyClaim] = {}
        #: key_index -> the TOPIC box that holds it (ADR-0082). A boxed key is
        #: unavailable to any other box; it IS available to that box's own
        #: subtopic `KeyClaim`s.
        self._boxed: dict[int, KeyBox] = {}
        self._next_box_id = 0
        self._released = asyncio.Condition()

    @property
    def key_count(self) -> int:
        return self._key_count

    def is_free(self, key_index: int, *, claim: KeyClaim | None = None) -> bool:
        """True when `key_index` is unowned, or owned by `claim` itself."""

        holder = self._claimed.get(key_index)
        return holder is None or holder is claim

    def free_keys(self, *, claim: KeyClaim | None = None) -> list[int]:
        return [k for k in range(self._key_count) if self.is_free(k, claim=claim)]

    def claimable_keys(self, claim: KeyClaim) -> list[int]:
        """The keys `claim` may bind: unowned (or already its own), and inside
        its box if it has one (ADR-0082).

        This is the single place the box narrows the ladder. Every scan in
        `_acquire_for_claim` -- the first bind and the move to a fresher key
        alike -- goes through it, so "a topic never touches another topic's
        key" holds by construction rather than by each scan remembering to
        check.
        """

        candidates = (
            sorted(claim.box.key_indices) if claim.box is not None else range(self._key_count)
        )
        return [k for k in candidates if self.is_free(k, claim=claim)]

    def _boxable(self, key_index: int) -> bool:
        """A key in no box and bound by no claim -- available to a new box."""

        return key_index not in self._boxed and self._claimed.get(key_index) is None

    def lease_box(self, size: int, *, prefer: list[int] | None = None) -> KeyBox:
        """Hand a topic a box of up to `size` currently-unboxed keys for its
        whole run (ADR-0082), coldest first per `prefer`.

        Takes FEWER -- possibly zero -- when the pool is that tight. The worker
        admits at most `pool // box_size` topics precisely so this doesn't
        normally happen, but a short box is not an error: a topic with a few
        keys still makes progress, where refusing to start would just idle them.
        `prefer` is a ledger-derived least-spent-first order from
        `GeminiContentGenerator`; keys it omits (or `None` -- a backend with no
        ledger) fall back to index order.
        """

        self._next_box_id += 1
        box = KeyBox(box_id=self._next_box_id)
        boxable = {k for k in range(self._key_count) if self._boxable(k)}
        ordered = [k for k in (prefer or []) if k in boxable]
        ordered += [k for k in sorted(boxable) if k not in set(ordered)]
        for key_index in ordered[: max(0, size)]:
            self._boxed[key_index] = box
            box.key_indices.add(key_index)
        return box

    async def release_box(self, box: KeyBox) -> None:
        """Return every key a box holds to the pool (ADR-0082). Also drops any
        still-bound claim on those keys -- a run that dies mid-branch must not
        leave a key owned by a claim whose scope has gone."""

        for key_index in list(box.key_indices):
            self._boxed.pop(key_index, None)
            holder = self._claimed.get(key_index)
            if holder is not None and holder.box is box:
                del self._claimed[key_index]
                holder.key_index = None
        box.key_indices.clear()
        async with self._released:
            self._released.notify_all()

    def bind(self, claim: KeyClaim, key_index: int) -> None:
        """Move `claim` onto `key_index`, releasing whatever it held before.

        Raises if the key is already owned by someone else: a caller reaching
        this with a contended key means the scan that chose it read a stale
        free-list, and silently sharing the key is the one outcome this whole
        design exists to prevent.
        """

        if not self.is_free(key_index, claim=claim):
            raise RuntimeError(f"key {key_index} is already claimed")
        previous = claim.key_index
        if previous is not None and self._claimed.get(previous) is claim:
            del self._claimed[previous]
        self._claimed[key_index] = claim
        claim.key_index = key_index

    async def release(self, claim: KeyClaim) -> None:
        held = claim.key_index
        claim.key_index = None
        if held is None or self._claimed.get(held) is not claim:
            return
        del self._claimed[held]
        async with self._released:
            self._released.notify_all()

    async def wait_for_release(self, *, max_wait_s: float) -> None:
        """Block until some key is released, or `timeout` elapses.

        The cap is not a safety net over a lost wakeup -- it is how a
        caller that is ALSO waiting on an rpm window gets to re-check that
        window. A group can be waiting for two different things at once (no
        free key, and its own key's minute not yet over), and only one of them
        produces an event.
        """

        async with self._released:
            try:
                await asyncio.wait_for(self._released.wait(), max_wait_s)
            except TimeoutError:
                return


@dataclass(frozen=True)
class _ClaimWait:
    """Why a claim-aware acquire found nothing, and for how long to wait.

    The three causes are kept apart rather than reported as one "no cell
    available": a key held by another subtopic group, a cell inside its own
    rpm minute, and a cell parked by a provider cooldown are different facts
    with different fixes -- more keys, more time, and a provider problem
    respectively. Collapsing them is how a throttled run gets read as a
    contended one and answered by buying keys that were never the constraint.
    """

    seconds: float
    #: Keys held by a DIFFERENT unit of work. Excludes this claim's own key,
    #: which is never something it could be waiting for.
    other_claims: int
    #: Keys held by nobody -- what this claim could move onto if their cells had
    #: room. Non-zero here with no grant means those cells were throttled or
    #: spent, NOT that the pool was busy.
    free_keys: int
    #: DISTINCT cells with daily budget but no window right now. Counted per
    #: cell, not per visit: the scan can look at one cell several times over
    #: (own preferred rungs, then the free-key sweep, then the deferred rung),
    #: and "3 cells throttled" when one cell was checked three times is the
    #: same species of untrue as the message this field exists to fix.
    throttled_cells: int

    @property
    def waiting_on_a_key(self) -> bool:
        """True when nothing but another unit finishing can help. With no
        throttled cell seen, no deadline exists to wait out -- only a release."""

        return self.throttled_cells == 0


@dataclass(frozen=True)
class _CellAttempt:
    """What `_try_take_cell` found. `exhausted` means this cell's DAY is gone,
    so it must not count toward "somewhere still has room"; `wait_s` means the
    cell has budget but no window right now, and says when it might."""

    granted: bool = False
    exhausted: bool = False
    wait_s: float | None = None


#: The key claim in force for the current task (ADR-0074), or None outside any
#: claimed scope. A `ContextVar` rather than a `ContentGenerator` argument on
#: purpose: which key a call runs on is a quota concern, and threading it
#: through `generate_cards`/`correct_cards`/`generate_questions` would put a
#: backend-specific parameter on the one interface the whole codebase shares --
#: `fake` has no keys to claim, and the pipeline should not know that `gemini`
#: does. asyncio copies the context into every task it creates, so a claim set
#: at the top of a LangGraph branch is inherited by every call that branch makes,
#: including the ones it fans out with `asyncio.gather`, and by nothing else.
CURRENT_KEY_CLAIM: ContextVar[KeyClaim | None] = ContextVar("spoin_current_key_claim", default=None)


#: `acquire()` uses this internally to say "no cell right now, and the reason is
#: contention rather than exhaustion" -- the caller should wait for a key to be
#: released and try again. Never returned to callers outside this module.
_WAIT_FOR_KEY = "wait-for-key"


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
    #: How many rungs at the END of `ladder` are a RESERVE (ADR-0074): reached
    #: only when no key anywhere has daily room on an ordinary rung, never to
    #: work around keys merely being claimed. Only meaningful on a claim-aware
    #: acquire; an unclaimed call walks the whole ladder as it always has.
    reserve_rungs: int = 0
    #: Shared with this generator's OTHER pool -- a key is claimed for a unit of
    #: work across both. `None` disables claim-aware acquisition entirely, which
    #: is what every test and the `fake` backend get.
    claims: KeyClaimRegistry | None = None
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
    #: (key_index, model) -> the rpm this cell is currently allowed, which is
    #: NOT `rung.rpm` once the provider has disagreed with us (ADR-0065).
    #: Absent means "never throttled, use the configured ceiling".
    #:
    #: `rung.rpm` is a number a human read off a docs page; it is a claim about
    #: the provider's limit, and a 77%-rejection run is that claim being wrong
    #: out loud. AIMD replaces the claim with a measurement: halve on a
    #: per-minute 429, add one back per success, floor at 1. It converges on
    #: whatever the real ceiling is without anyone having to know why the
    #: configured one was wrong -- shared project across keys, an undocumented
    #: burst limit, a limit the provider changed on Tuesday.
    #:
    #: In-memory, unlike the window itself (ADR-0058 put that in the database
    #: because two processes each permitting the full ceiling is precisely the
    #: bug). Accepted difference: this value changes on nearly every call, and
    #: it re-converges within a minute of traffic, so persisting it would buy a
    #: write per call to save at most a minute of relearning per process. If
    #: two processes ever diverge badly enough to matter, the shared window is
    #: still the thing that actually enforces the ceiling -- this only decides
    #: how eagerly each one walks toward it.
    _effective_rpm: dict[tuple[int, str], float] = field(
        default_factory=dict, init=False, repr=False
    )

    def __post_init__(self) -> None:
        if self.key_count < 1:
            raise ValueError("QuotaGovernor needs at least one key")
        if not self.ladder:
            raise ValueError("QuotaGovernor needs at least one ladder rung")
        if self.reserve_rungs < 0:
            raise ValueError(f"reserve_rungs cannot be negative, got {self.reserve_rungs}")
        # A ladder that is ALL reserve has no ordinary rung to exhaust, so the
        # reserve's own entry condition could never be met and the pool would
        # refuse every call while holding full quota. Clamped rather than
        # rejected: the reserve is a request about a ladder whose length is
        # configured separately (and shortened for real -- a retired model id,
        # a test pool of one), so a ladder too short to hold one is a ladder
        # without a reserve, not a broken configuration.
        keepable = max(0, len(self.ladder) - 1)
        if self.reserve_rungs > keepable:
            logger.warning(
                "quota: reserve_rungs=%d but the ladder has only %d rung(s) -- holding %d back "
                "so at least one ordinary rung remains",
                self.reserve_rungs,
                len(self.ladder),
                keepable,
            )
            self.reserve_rungs = keepable

    @property
    def _ordinary_rungs(self) -> list[LadderRung]:
        return self.ladder[: len(self.ladder) - self.reserve_rungs]

    @property
    def _reserve_ladder(self) -> list[LadderRung]:
        return self.ladder[len(self.ladder) - self.reserve_rungs :] if self.reserve_rungs else []

    async def acquire(
        self,
        *,
        now: datetime,
        exclude_models: frozenset[str] = frozenset(),
        claim: KeyClaim | None = None,
    ) -> tuple[int, str]:
        """A cell to make the next call on.

        With no `claim` this is the original per-call scan: best model first,
        least-spent key within it (ADR-0028/0065). With one, it is ADR-0074's
        own-key-first order, and a call that finds every key claimed WAITS for
        one to free rather than sharing.

        That wait happens outside `self._lock`, unlike the rpm wait inside
        `_acquire_locked`. It has to: the event this caller is waiting for is
        another unit of work releasing a key, and releasing happens on the far
        side of that unit's own `acquire()` calls. Holding the pool lock across
        it would make the waiter block the only thing that could wake it.
        """

        if claim is None or self.claims is None:
            async with self._lock, session_scope() as session:
                await self.prune_request_window(session, now=now)
                return await self._acquire_locked(session, now=now, exclude_models=exclude_models)

        while True:
            async with self._lock, session_scope() as session:
                await self.prune_request_window(session, now=now)
                outcome = await self._acquire_for_claim(
                    session, now=now, exclude_models=exclude_models, claim=claim
                )
            if isinstance(outcome, tuple):
                return outcome
            # Reports what was OBSERVED, never a diagnosis: an earlier version of
            # this line asserted "every key is claimed" on every fall-through,
            # including the common case where keys were free and their cells were
            # simply inside their own minute. A log that names the wrong cause
            # sends the reader to buy keys for a throttling problem.
            logger.info(
                "quota: no cell for this claim right now -- %d key(s) held by other work, "
                "%d unclaimed, %d cell(s) with budget but no window; waiting up to %.1fs %s",
                outcome.other_claims,
                outcome.free_keys,
                outcome.throttled_cells,
                outcome.seconds,
                "for a key to be released"
                if outcome.waiting_on_a_key
                else "for a key or the earliest window",
            )
            await self.claims.wait_for_release(max_wait_s=outcome.seconds)
            now = datetime.now(UTC)

    async def acquire_for_claim_with_session(
        self,
        session: AsyncSession,
        *,
        now: datetime,
        claim: KeyClaim,
        exclude_models: frozenset[str] = frozenset(),
    ) -> tuple[int, str] | _ClaimWait:
        """One pass of ADR-0074's ladder on a caller-supplied session, with no
        waiting -- a granted cell, or the seconds a real `acquire()` would wait.

        Exists for the same reason the other `_with_session` variants do (the
        fixture session IS the isolation boundary), plus one of its own: the
        wait outcome is a decision worth asserting on, and it is invisible from
        `acquire()`, which loops until it turns into a grant.
        """

        async with self._lock:
            return await self._acquire_for_claim(
                session, now=now, exclude_models=exclude_models, claim=claim
            )

    async def _acquire_for_claim(
        self,
        session: AsyncSession,
        *,
        now: datetime,
        exclude_models: frozenset[str],
        claim: KeyClaim,
    ) -> tuple[int, str] | _ClaimWait:
        """ADR-0074's ladder for a unit of work that owns a key. Returns either
        a granted cell or how long to wait before asking again.

        The order, for a claim holding key X:

        1. X's preferred rungs -- every ordinary rung but the last.
        2. Any UNCLAIMED key's preferred rungs, least-spent first. The claim
           moves to that key; this is what stops a group stranding itself on a
           key whose strong models are spent.
        3. X's last ordinary rung.
        4. Any unclaimed key, all ordinary rungs.
        5. The reserve -- ONLY if no key anywhere still has daily room on an
           ordinary rung. A reserve rung is for a spent day, never for a busy
           one.
        6. Otherwise wait: room exists somewhere, it is just claimed or
           throttled right now.

        Steps 1 and 3 deliberately prefer X's *second* model over another key's
        best one. Keeping a unit of work on one key for its whole run is the
        entire point of the claim -- one caller per key means no cell can be
        raced, which is what makes an rpm violation structurally impossible
        rather than merely counted.

        **"Any unclaimed key" means "any unclaimed key in this claim's BOX"**
        when it has one (ADR-0082) -- steps 2 and 4, step 5's escalation, and
        the "is the day actually gone?" test that gates it. So does the wait at
        step 6: a boxed claim waits for a SIBLING subtopic group of its own
        topic to finish, never for another topic. Without a box the scope is the
        whole pool, exactly as ADR-0074 wrote it.
        """

        # Bound to a local because the nested scans below close over it --
        # mypy will not carry an attribute's narrowing into a closure.
        claims = self.claims
        assert claims is not None
        #: The keys this claim can see at all (ADR-0082). Every "anywhere" below
        #: -- the free scan, the daily-room test, the wait counts -- is over
        #: THIS set, not `range(self.key_count)`.
        scope = (
            sorted(claim.box.key_indices) if claim.box is not None else list(range(self.key_count))
        )
        day = _day_start(now)
        unavailable = await self._unavailable_models(session, now=now)

        def usable(rungs: list[LadderRung]) -> list[LadderRung]:
            return [
                rung
                for rung in rungs
                if rung.model not in exclude_models and rung.model not in unavailable
            ]

        ordinary = usable(self._ordinary_rungs)
        reserve = usable(self._reserve_ladder)
        if not ordinary and not reserve:
            raise AllModelsUnavailableError(
                f"All {len(self.ladder)} model(s) unavailable -- provider outage, not quota; "
                f"the day's ledger was never consulted"
            )

        preferred, deferred = (
            (ordinary[:-1], ordinary[-1:]) if len(ordinary) > 1 else (ordinary, [])
        )
        #: Keyed by CELL so a cell seen twice counts once -- see `_ClaimWait`.
        waits: dict[tuple[int, str], float] = {}

        async def take(key_index: int, rungs: list[LadderRung]) -> tuple[int, str] | None:
            for rung in rungs:
                attempt = await self._try_take_cell(session, day, key_index, rung, now=now)
                if attempt.wait_s is not None:
                    waits[(key_index, rung.model)] = attempt.wait_s
                if attempt.granted:
                    # A non-sticky claim (ADR-0074 pin off) never binds: it
                    # keeps `key_index` None so the next call re-scans the box
                    # least-spent-first instead of returning here.
                    if claim.sticky:
                        claims.bind(claim, key_index)
                    return key_index, rung.model
            return None

        async def take_free(rungs: list[LadderRung]) -> tuple[int, str] | None:
            #: Model-major, least-spent key within each rung -- the same order an
            #: unclaimed acquire uses, restricted to keys nobody owns (and, with
            #: a box, to that box's keys).
            for rung in rungs:
                spent = await self._rung_spend(session, day, rung.model)
                for key_index in sorted(
                    claims.claimable_keys(claim), key=lambda k: (spent.get(k, 0), k)
                ):
                    granted = await take(key_index, [rung])
                    if granted is not None:
                        return granted
            return None

        if claim.key_index is not None:
            granted = await take(claim.key_index, preferred)
            if granted is not None:
                return granted

        granted = await take_free(preferred)
        if granted is not None:
            return granted

        if claim.key_index is not None and deferred:
            granted = await take(claim.key_index, deferred)
            if granted is not None:
                return granted

        granted = await take_free(ordinary)
        if granted is not None:
            return granted

        if not await self._any_daily_room(session, day, ordinary, scope):
            if not reserve:
                raise DailyQuotaExhaustedError(
                    f"All {len(scope)} key(s) available to this claim exhausted across "
                    f"{len(ordinary)} ordinary model(s) for {day.date()}, and no reserve "
                    f"rung is configured"
                )
            logger.warning(
                "quota: no key has daily room on any ordinary rung -- falling back to the "
                "reserve ladder (%s). The day's thinking budget is spent, not merely busy.",
                ", ".join(rung.model for rung in reserve),
            )
            if claim.key_index is not None:
                granted = await take(claim.key_index, reserve)
                if granted is not None:
                    return granted
            granted = await take_free(reserve)
            if granted is not None:
                return granted
            if not await self._any_daily_room(session, day, reserve, scope):
                raise DailyQuotaExhaustedError(
                    f"All {len(scope)} key(s) available to this claim exhausted across "
                    f"{len(ordinary) + len(reserve)} model(s) for {day.date()}, "
                    f"reserve included"
                )

        # Somewhere has budget; it is claimed by another unit of work, in a
        # cooldown, or inside its own minute. `waits` only covers cells this
        # scan actually looked at -- a key held by someone else is never
        # examined, so its release has no deadline to offer and the cap is what
        # bounds the wait instead. Which of the three it was travels with the
        # duration; see `_ClaimWait` for why that is not one fact.
        # Both counts EXCLUDE this claim's own key: it is neither something to
        # wait for nor somewhere to move to, and counting it as "free" is what
        # made an earlier version of the log read "1 free" about a key that had
        # just refused the call.
        # Counted over `scope`, so a boxed claim's log line is about ITS topic:
        # "12 held by sibling groups, 3 unclaimed" is actionable; the same line
        # about all 119 keys would be describing work this claim cannot wait for
        # and cannot use.
        unowned = sum(1 for key in scope if claims.is_free(key))
        held_by_me = 1 if claim.key_index is not None else 0
        return _ClaimWait(
            seconds=max(0.5, min(min(waits.values()) + 0.2 if waits else 5.0, 60.0)),
            other_claims=len(scope) - unowned - held_by_me,
            free_keys=unowned,
            throttled_cells=len(waits),
        )

    async def _any_daily_room(
        self, session: AsyncSession, day: datetime, rungs: list[LadderRung], keys: list[int]
    ) -> bool:
        """Whether any key in `keys` still has daily budget on any of `rungs` --
        including keys another unit of work currently holds.

        Claimed-but-unspent is the whole distinction the reserve turns on: that
        key's budget is real, it is simply busy, and waiting a few seconds for
        it is right where spending the weakest model on the same call is wrong.

        `keys` is the caller's SCOPE, not a filter for convenience: for a boxed
        claim (ADR-0082) the day that matters is its box's day. Asking about the
        whole pool there would keep a topic whose own box is spent off the
        reserve rung for as long as any other topic still had budget -- it would
        wait out a contention that can never resolve in its favour.
        """

        for rung in rungs:
            spent = await self._rung_spend(session, day, rung.model)
            if any(spent.get(key_index, 0) < rung.rpd for key_index in keys):
                return True
        return False

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
        self,
        key_index: int,
        model: str,
        *,
        now: datetime,
        retry_after_s: float | None = None,
        shrink_rpm: bool = True,
    ) -> None:
        """A PER-MINUTE 429 (`GenerateRequestsPerMinutePerProjectPerModel`) --
        this cell has daily quota left and is simply being throttled right now.

        Three things happen, and they are three different time horizons:

        1. **The cell is parked** until `retry_after_s` has passed, which
           `_acquire_locked` waits out via its `candidate_wait_times` queue.
        2. **The day's charge is REFUNDED** (ADR-0065). `acquire()` bills RPD
           when it grants a cell, but the provider does not count a request it
           refused -- so a throttled call left the day's ledger a request poorer
           for nothing. Measured live before this changed: 727 throttles inside
           16 minutes, every one of them a permanent RPD unit spent on zero
           output, on a thinking ladder whose entire daily budget is 20 per
           cell. ADR-0058 knowingly accepted that over-count because ledger
           erosion was the only thing terminating the throttle-retry loop; that
           loop now terminates on a measured throttle streak instead
           (`_invoke_with_retry`), so the erosion has nothing left to buy.
        3. **The cell's effective rpm is halved** -- BUT only when `shrink_rpm`
           is set, i.e. the 429 actually identified itself as per-minute (a
           `quotaId` or a short `RetryInfo`). Google has been returning bare
           `RESOURCE_EXHAUSTED` with no scope for every 429; halving on that
           guess (ADR-0060) walked healthy cells down to the 1-rpm floor over a
           run and the pool's throughput decayed with it. A guessed per-minute
           429 still parks the cell and refunds the day -- it just no longer
           also ratchets the ceiling down on no evidence. See `_effective_rpm`.

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
                session, key_index, model, now=now, delay=delay, shrink_rpm=shrink_rpm
            )

    async def mark_rate_limited_with_session(
        self,
        session: AsyncSession,
        key_index: int,
        model: str,
        *,
        now: datetime,
        retry_after_s: float | None = None,
        shrink_rpm: bool = True,
    ) -> None:
        """Same as `mark_rate_limited`, reusing a caller-supplied session — for
        tests, same reasoning as `acquire_with_session`."""

        delay = retry_after_s if retry_after_s is not None else _DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS
        await self._mark_rate_limited_with_session(
            session, key_index, model, now=now, delay=delay, shrink_rpm=shrink_rpm
        )

    async def _mark_rate_limited_with_session(
        self,
        session: AsyncSession,
        key_index: int,
        model: str,
        *,
        now: datetime,
        delay: float,
        shrink_rpm: bool = True,
    ) -> None:
        ledger = await self._ledger_row(session, _day_start(now), key_index, model)
        ledger.cooldown_until = now + timedelta(seconds=delay)
        # Floored at 0 rather than allowed to go negative: a refund with no
        # matching grant (a retry on a cell granted before a restart, a test
        # calling this directly) is a bookkeeping edge, not a reason to invent
        # daily budget that was never spent.
        if ledger.requests_spent > 0:
            ledger.requests_spent -= 1
            # A cell that had hit its ceiling and is now one below it is
            # genuinely usable again -- leaving `exhausted_at` set would keep
            # `mark_exhausted`'s retirement in force over a charge we just
            # agreed was never consumed.
            if ledger.exhausted_at is not None and ledger.requests_spent < self._rpd_for(model):
                ledger.exhausted_at = None
        if shrink_rpm:
            self._shrink_effective_rpm(key_index, model)
        await session.flush()
        logger.info(
            "quota: key %d model %s hit a per-minute rate limit -- cooling down %.1fs "
            "(day's charge refunded, now %d spent)",
            key_index,
            model,
            delay,
            ledger.requests_spent,
        )

    def _rpd_for(self, model: str) -> int:
        rung = next((r for r in self.ladder if r.model == model), None)
        return rung.rpd if rung is not None else 0

    def _shrink_effective_rpm(self, key_index: int, model: str) -> None:
        """Multiplicative decrease (the MD of AIMD): the provider refused a call
        this cell's window said there was room for, so the window is too wide.
        Halving rather than stepping down by one because we do not know how far
        wrong we are -- overshooting downward costs a little latency, while
        creeping down one at a time keeps paying the same 429 all the way."""

        rung = next((r for r in self.ladder if r.model == model), None)
        if rung is None:
            return
        cell = (key_index, model)
        current = self._effective_rpm.get(cell, float(rung.rpm))
        shrunk = max(_EFFECTIVE_RPM_FLOOR, current / 2.0)
        if shrunk == current:
            return
        self._effective_rpm[cell] = shrunk
        logger.info(
            "quota: key %d model %s throttled -- effective rpm %.1f -> %.1f (configured %d)",
            key_index,
            model,
            current,
            shrunk,
            rung.rpm,
        )

    def note_call_succeeded(self, key_index: int, model: str) -> None:
        """Additive increase (the AI of AIMD): a call got through, so the cell
        can carry a little more than we last believed. One per success, capped
        at the configured `rung.rpm` -- the measurement only ever explains why
        the documented ceiling is too HIGH, never grounds for exceeding it.

        A no-op for a cell that has never been throttled: there is nothing to
        grow back, and the configured ceiling already applies."""

        cell = (key_index, model)
        current = self._effective_rpm.get(cell)
        if current is None:
            return
        rung = next((r for r in self.ladder if r.model == model), None)
        if rung is None:
            return
        grown = min(float(rung.rpm), current + 1.0)
        if grown == current:
            return
        self._effective_rpm[cell] = grown
        logger.debug(
            "quota: key %d model %s recovered -- effective rpm %.1f -> %.1f",
            key_index,
            model,
            current,
            grown,
        )

    def effective_rpm(self, key_index: int, model: str) -> int:
        """The rpm this cell is currently allowed -- the configured ceiling
        until the provider has said otherwise. Integer because the window
        counts whole requests; a cell shrunk below 1 would be shut out entirely
        rather than throttled, hence `_shrink_effective_rpm`'s floor."""

        rung = next((r for r in self.ladder if r.model == model), None)
        if rung is None:
            return 0
        return int(self._effective_rpm.get((key_index, model), float(rung.rpm)))

    def is_at_rpm_floor(self, key_index: int, model: str) -> bool:
        """Whether this cell has already been paced down as far as AIMD goes.

        The distinction `_invoke_with_retry` needs to read a 429 correctly: a
        throttle on a cell we had not yet slowed down is evidence our PACING was
        wrong, and the fix is to slow down. A throttle on a cell already at one
        request per minute is evidence about the PROVIDER -- there is no slower
        we can go, so retrying is no longer a plan."""

        return self._effective_rpm.get((key_index, model), float("inf")) <= _EFFECTIVE_RPM_FLOOR

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
            unavailable = await self._unavailable_models(session, now=now)
            skipped_rungs: list[str] = []

            for rung in self.ladder:
                if rung.model in exclude_models:
                    logger.debug("quota: model %s excluded for this call, skipping", rung.model)
                    skipped_rungs.append(rung.model)
                    continue
                if rung.model in unavailable:
                    logger.debug(
                        "quota: model %s excluded pending a recovery probe, skipping", rung.model
                    )
                    skipped_rungs.append(rung.model)
                    continue
                # LEAST-SPENT FIRST, not key 0 first (ADR-0065). A plain
                # `range(key_count)` returns the lowest-numbered key that
                # happens to be free, so key 0 absorbs every call the moment it
                # comes off cooldown and the scan never has a reason to walk
                # past it. Measured live: key 0 at 380/500 on a model where
                # keys 10-32 sat at 15/500 all afternoon, having been granted
                # once each during one early burst and never revisited.
                #
                # Ordering by spend instead makes the skew self-correcting
                # rather than self-reinforcing, and it balances across
                # PROCESSES too -- the API and the worker read the same ledger,
                # so neither has to know the other exists to stop colliding
                # with it. `key_index` breaks ties so the choice stays
                # deterministic for a given ledger state.
                spent = await self._rung_spend(session, day, rung.model)
                for key_index in sorted(range(self.key_count), key=lambda k: (spent.get(k, 0), k)):
                    attempt = await self._try_take_cell(session, day, key_index, rung, now=now)
                    if attempt.exhausted:
                        continue
                    has_unexhausted_cell = True
                    if attempt.granted:
                        return key_index, rung.model
                    if attempt.wait_s is not None:
                        candidate_wait_times.append(attempt.wait_s)

            if not has_unexhausted_cell:
                # Two genuinely different endings, told apart by whether any
                # rung was ever CHECKED (ADR-0065). Every rung skipped as
                # unavailable means no model was even asked about its quota --
                # reporting that as "everything is exhausted" is how a 504
                # storm got written up as daily quota death with 90% of the
                # grid untouched.
                if len(skipped_rungs) == len(self.ladder):
                    logger.warning(
                        "quota: every model in the ladder is excluded as unavailable (%s) -- "
                        "no rung was checked for quota at all",
                        ", ".join(skipped_rungs),
                    )
                    raise AllModelsUnavailableError(
                        f"All {len(self.ladder)} model(s) unavailable "
                        f"({', '.join(skipped_rungs)}) -- provider outage, not quota; "
                        f"the day's ledger was never consulted"
                    )
                checked = len(self.ladder) - len(skipped_rungs)
                excluded_note = (
                    f" ({len(skipped_rungs)} further model(s) skipped as unavailable: "
                    f"{', '.join(skipped_rungs)})"
                    if skipped_rungs
                    else ""
                )
                logger.warning(
                    "quota: all %d key(s) exhausted across %d checked model(s) for %s%s",
                    self.key_count,
                    checked,
                    day.date(),
                    excluded_note,
                )
                raise DailyQuotaExhaustedError(
                    f"All {self.key_count} key(s) exhausted across {checked} checked "
                    f"model(s) for {day.date()}{excluded_note}"
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

    async def exclude_model(
        self, model: str, *, now: datetime, expires_in_s: float, reason: str
    ) -> None:
        """Stop routing real traffic to `model` -- called the moment a call
        times out (see langchain_impl.py's `DeadlineExceeded` handler), before
        the background probe even starts, so nothing else pays that same
        timeout while recovery is being checked.

        Persisted since ADR-0065, for the reason ADR-0058 persisted the RPM
        window: this used to be an in-memory set per `QuotaGovernor`, so the
        API process, the worker process, and the two pools within each of them
        all held separate views. A 504 outage on a model both ladders list was
        therefore rediscovered up to four times over, each rediscovery costing
        a full request timeout.

        `expires_in_s` should be the caller's probe budget -- see
        `ModelUnavailable.expires_at` for why an exclusion has to be able to
        outlive the process that wrote it without outliving it forever."""

        async with session_scope() as session:
            await self.exclude_model_with_session(
                session, model, now=now, expires_in_s=expires_in_s, reason=reason
            )

    async def exclude_model_with_session(
        self,
        session: AsyncSession,
        model: str,
        *,
        now: datetime,
        expires_in_s: float,
        reason: str,
    ) -> None:
        """Same as `exclude_model`, reusing a caller-supplied session — for
        tests, same reasoning as `acquire_with_session`."""

        row = await session.get(ModelUnavailable, model)
        expires_at = now + timedelta(seconds=expires_in_s)
        if row is None:
            session.add(
                ModelUnavailable(
                    model=model,
                    excluded_at=now,
                    expires_at=expires_at,
                    reason=reason[:256],
                )
            )
        else:
            # Re-exclusion pushes the horizon out rather than leaving the
            # original one standing: the model failing again NOW is fresh
            # evidence, and an expiry anchored to the first failure would let a
            # still-dead model quietly come back into rotation mid-outage.
            row.excluded_at = now
            row.expires_at = expires_at
            row.reason = reason[:256]
        await session.flush()

    async def include_model(self, model: str) -> None:
        """Reverses `exclude_model` -- called by the probe either on success
        (model responded again) or once it gives up (every key it tried is
        separately marked exhausted via `mark_exhausted`, so the ledger itself
        keeps those cells out of rotation for the rest of today; releasing the
        flag here only matters for any key the probe didn't get to)."""

        async with session_scope() as session:
            await self.include_model_with_session(session, model)

    async def include_model_with_session(self, session: AsyncSession, model: str) -> None:
        """Same as `include_model`, reusing a caller-supplied session."""

        await session.execute(delete(ModelUnavailable).where(ModelUnavailable.model == model))
        await session.flush()

    async def _unavailable_models(self, session: AsyncSession, *, now: datetime) -> set[str]:
        """Models currently parked out of rotation. An expired row is ignored
        rather than deleted here: the read path shouldn't take a write lock,
        and a stale row is harmless once it stops being believed. `acquire()`'s
        own prune sweep is where it goes."""

        rows = await session.scalars(
            select(ModelUnavailable.model).where(ModelUnavailable.expires_at > now)
        )
        return set(rows.all())

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
            # Plain `FOR UPDATE`, not SKIP LOCKED: same short-transaction claim
            # shape as the worker's job claim (`worker/__main__.py`) -- lock the
            # one oldest unconfirmed reservation, flip `confirmed`, flush. A
            # concurrent confirm on the same backend blocks briefly, then re-reads
            # and picks the next unconfirmed row. SKIP LOCKED was dropped because
            # on CockroachDB it can skip a freshly-committed, unlocked row (0016
            # spike); with `LIMIT 1` on an unindexed `confirmed` predicate it can
            # also over-lock the scan. Neither matters here -- the lock is held
            # for microseconds.
            .with_for_update()
        )
        if reservation is None:
            session.add(QuotaRequest(backend=backend, sent_at=now, confirmed=True))
        else:
            reservation.sent_at = now
            reservation.confirmed = True
        await session.flush()

    async def _try_take_cell(
        self,
        session: AsyncSession,
        day: datetime,
        key_index: int,
        rung: LadderRung,
        *,
        now: datetime,
    ) -> _CellAttempt:
        """Take one (key, model) cell if it has room, reporting why if not.

        Extracted so the ladder-order scan (`_acquire_locked`) and the
        claim-order scan (`_acquire_for_claim`, ADR-0074) enforce quota through
        the same code rather than two implementations free to drift apart -- the
        order they visit cells in differs, what makes a cell takeable does not.

        Rows are read, never created, on the way past: a cell only gets a ledger
        row once it is actually GRANTED. That keeps "a row exists" meaning "this
        cell was used" rather than "this cell was looked at" -- the property that
        made it possible to prove, from the ledger alone, that a first-fit scan
        never reached key 10 (ADR-0065).
        """

        ledger = await self._existing_ledger_row(session, day, key_index, rung.model)
        if ledger is not None and ledger.requests_spent >= rung.rpd:
            logger.debug(
                "quota: key %d model %s already exhausted for %s (%d/%d), trying next",
                key_index,
                rung.model,
                day.date(),
                ledger.requests_spent,
                rung.rpd,
            )
            return _CellAttempt(exhausted=True)

        if ledger is not None and ledger.cooldown_until is not None and now < ledger.cooldown_until:
            wait_cd = (ledger.cooldown_until - now).total_seconds()
            logger.debug(
                "quota: key %d model %s is in a rate-limit cooldown (%.1fs remaining), trying next",
                key_index,
                rung.model,
                wait_cd,
            )
            return _CellAttempt(wait_s=wait_cd)

        # Claims the RPM slot as part of the same check -- see
        # `_try_reserve_rpm` for why those cannot be two statements.
        if not await self._try_reserve_rpm(session, key_index, rung, now=now):
            earliest = await self._earliest_send_in_window(session, key_index, rung.model, now=now)
            wait_rpm: float | None = None
            if earliest is not None:
                pending = (earliest + timedelta(seconds=_RPM_WINDOW_SECONDS) - now).total_seconds()
                if pending > 0:
                    wait_rpm = pending
            logger.debug(
                "quota: key %d model %s at RPM ceiling (%d/min), trying next",
                key_index,
                rung.model,
                self.effective_rpm(key_index, rung.model),
            )
            return _CellAttempt(wait_s=wait_rpm)

        if ledger is None:
            ledger = await self._ledger_row(session, day, key_index, rung.model)
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
        return _CellAttempt(granted=True)

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

        The ceiling compared against is this cell's LEARNED rpm, not the
        configured one (ADR-0065) -- see `_effective_rpm`.
        """

        ceiling = self.effective_rpm(key_index, rung.model)
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
                ).where(in_window < ceiling),
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

        **This prune refunds never-sent grants; throttled sends are refunded
        elsewhere** (`mark_rate_limited`, ADR-0065) and for a different reason:
        a phantom is a grant that never became a request, a throttle is a
        request the provider refused to count. Both are RPD the day never
        actually spent, but only one of them is discoverable by aging a row
        out, so they are two mechanisms rather than one.

        This used to be the ONLY refund, deliberately: ADR-0058 accepted the
        throttle over-count because ledger erosion was the sole terminator for
        `_invoke_with_retry`'s per-minute branch, which retries without burning
        a cell (and ADR-0060 widened the path into it by routing unidentifiable
        429s there too). That loop now stops on a measured throttle streak, so
        the erosion buys nothing and costs real quota -- see ADR-0065.

        **A cell already marked exhausted is left alone**, so bookkeeping can
        never resurrect one that `mark_exhausted` deliberately retired for the
        day.
        """

        dropped = (
            await session.execute(
                delete(QuotaRequest)
                .where(QuotaRequest.sent_at < now - timedelta(seconds=_REQUEST_RETENTION_SECONDS))
                .returning(QuotaRequest.backend, QuotaRequest.sent_at, QuotaRequest.confirmed)
            )
        ).all()

        # Exclusions whose probe never came back to clear them (ADR-0065).
        # Same disposable posture as the rows above: once an exclusion stops
        # being believed it has no history value, and leaving it would make
        # `SELECT * FROM model_unavailable` read as an outage that ended hours
        # ago.
        await session.execute(delete(ModelUnavailable).where(ModelUnavailable.expires_at <= now))

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

    async def _rung_spend(self, session: AsyncSession, day: datetime, model: str) -> dict[int, int]:
        """`key_index -> requests_spent` for one model, in ONE query instead of
        `key_count` row reads. A key with no row has never been granted this
        cell today, so it is absent -- and absent sorts as 0, which is both
        true and exactly the ordering we want: an untouched key is the emptiest
        key there is."""

        backends = {_backend(k, model): k for k in range(self.key_count)}
        rows = await session.execute(
            select(QuotaLedger.backend, QuotaLedger.requests_spent).where(
                QuotaLedger.day == day, QuotaLedger.backend.in_(backends)
            )
        )
        return {backends[backend]: spent for backend, spent in rows.all()}

    async def _existing_ledger_row(
        self, session: AsyncSession, day: datetime, key_index: int, model: str
    ) -> QuotaLedger | None:
        """The cell's row if it has one, without creating it. See
        `_acquire_locked`'s scan for why creation is deferred to the grant."""

        row: QuotaLedger | None = await session.scalar(
            select(QuotaLedger).where(
                QuotaLedger.day == day, QuotaLedger.backend == _backend(key_index, model)
            )
        )
        return row

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
