"""Quota primitives shared by the load balancer (ADR-0084).

This file used to be the `QuotaGovernor` — a DB-backed key x model grid built up
across ten ADRs to stay correct while several processes shared one key pool. The
generation pipeline is now the only process on the pool (ADR-0082/0084), so that
whole machinery is gone; what a person actually needs from it lives in
`load_balancer.py`.

What remains here is the vocabulary both sides still speak:

* the three `QuotaExhaustedError` subclasses the worker branches on (a spent day,
  a throttled minute, and a provider outage are different facts — CLAUDE.md);
* `LadderRung` / `parse_ladder` for `SPOIN_GEMINI_*_LADDER`;
* `KeyBox` (a topic's key slice + its balancer) and `BoxPool` (hands out
  disjoint slices) — all that survives `KeyClaimRegistry`, minus the per-group
  key pin ADR-0083 already retired.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from spoin.generation.load_balancer import LoadBalancer


class QuotaExhaustedError(RuntimeError):
    """A call could not be placed and will not be placeable soon.

    ADR-0003 §6: an expected outcome to degrade from, not a try/except accident.
    The worker (`apps/worker/__main__.py`) catches this and requeues the job as
    `pending` rather than `failed`, since `run_generation_pipeline` is idempotent
    (ADR-0026) and resumes once quota resets.

    **Never raised directly — always one of the three subclasses.** Folding them
    together made a provider outage get reported as daily-quota death with the
    ledger nearly untouched (ADR-0065).
    """


class DailyQuotaExhaustedError(QuotaExhaustedError):
    """Every `(key, model)` cell in scope has spent its RPD. Nothing more can be
    sent today; the cure is the daily reset."""


class AllCellsThrottledError(QuotaExhaustedError):
    """Every cell with daily budget left is in a per-minute cooldown, and has
    been long enough that waiting is indistinguishable from being stuck.
    Transient — a caller that stands down until midnight throws away quota it
    still has."""


class AllModelsUnavailableError(QuotaExhaustedError):
    """Every rung in the ladder is parked out of rotation (a 503 overload or a
    504 stall). Says nothing about quota; resolves when the provider does."""


@dataclass(frozen=True)
class LadderRung:
    """One model's place in a fallback ladder, and its own daily/per-minute
    caps — read off the provider's rate-limit page. List order IS priority:
    index 0 is tried first."""

    model: str
    rpd: int
    rpm: int


def parse_ladder(raw: str) -> list[LadderRung]:
    """Parses `"model:rpd:rpm,model:rpd:rpm,..."` (see `Settings.gemini_*_ladder`).

    A plain string, not a structured setting, for the same reason
    `gemini_api_keys` is: pydantic-settings JSON-parses list-typed env vars,
    which breaks an ordinary comma-separated value.
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
class KeyBox:
    """One topic's key slice for its whole generation run (ADR-0082), plus the
    `LoadBalancer` that schedules calls across it (ADR-0084).

    A box is fixed-size and closed: `settings.topic_key_box_size` keys, no
    borrowing outside it, no shared reserve. `pool // box_size` topics run at
    once, each on its own box. `balancer` is `None` for a backend with no key
    pool (`fake`, local) or when the pool had nothing free to lease.
    """

    box_id: int
    key_indices: tuple[int, ...] = ()
    balancer: LoadBalancer | None = None


class BoxPool:
    """Owns the pool's key indices and leases disjoint slices as boxes
    (ADR-0082). The top `remainder_size` indices are held back permanently for
    the claim-less path (topic matching, grading, the recovery probe), so a box
    and the remainder balancer can never share a key.

    All that survives `KeyClaimRegistry`: the box-allocation half. The per-group
    `KeyClaim` pin is gone (ADR-0083 retired it; ADR-0084 removed the class).
    In-process, single-owner — no lock, because `lease`/`release` are only ever
    called from `run_generation_pipeline`'s own (single-threaded) box setup.
    """

    def __init__(self, pool_size: int, *, remainder_size: int) -> None:
        if pool_size < 1:
            raise ValueError("BoxPool needs at least one key")
        if not 0 <= remainder_size < pool_size:
            raise ValueError(
                f"remainder_size {remainder_size} out of range for pool of {pool_size}"
            )
        self._pool_size = pool_size
        #: Indices a box may be cut from — everything below the remainder.
        self._boxable = list(range(pool_size - remainder_size))
        #: Held back for claim-less calls; never leased.
        self._remainder = list(range(pool_size - remainder_size, pool_size))
        self._boxed: set[int] = set()
        self._next_box_id = 0

    @property
    def remainder(self) -> tuple[int, ...]:
        return tuple(self._remainder)

    def lease(self, size: int, *, prefer: list[int] | None = None) -> tuple[int, tuple[int, ...]]:
        """`(box_id, key_indices)` for up to `size` currently-free boxable keys,
        `prefer` order first (a coldest-first list from the ledger), then index
        order. Fewer — possibly zero — when the boxable range is that tight;
        the worker admits at most `pool // box_size` topics so this stays rare,
        and a short box still generates."""

        self._next_box_id += 1
        free = [k for k in self._boxable if k not in self._boxed]
        free_set = set(free)
        order = [k for k in (prefer or []) if k in free_set]
        order += [k for k in free if k not in set(order)]
        take = tuple(order[: max(0, size)])
        self._boxed.update(take)
        return self._next_box_id, take

    def release(self, key_indices: tuple[int, ...]) -> None:
        self._boxed.difference_update(key_indices)
