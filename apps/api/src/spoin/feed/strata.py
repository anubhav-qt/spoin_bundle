"""Stratified allocation of a slate across difficulty tiers.

ADR-0010's central move: **the difficulty mix is a constraint, not a score.**

The instinct is to fold "should be 80% beginner" into the ranking function as a
weight. That produces approximately-80% that drifts with the candidate pool, and
it is untestable. Pulling each stratum as its own query and ranking *within* it
makes the mix exact and provable — which is what the functions below exist to do.

Principle: score individual items; enforce composition rules structurally.
"""

from __future__ import annotations

from dataclasses import dataclass

from spoin.core.config import DIFFICULTY_MIX
from spoin.domain.enums import Difficulty


def allocate(size: int, tier: Difficulty) -> dict[Difficulty, int]:
    """Split `size` slots across difficulties for a user at `tier`.

    Largest-remainder apportionment, so the parts always sum to exactly `size`.
    Naive rounding loses or gains a slot and turns "exactly 80%" back into
    "roughly 80%", which is the thing this whole approach exists to avoid.
    """

    mix = DIFFICULTY_MIX[tier]
    exact = {difficulty: size * share for difficulty, share in mix.items()}
    counts = {difficulty: int(value) for difficulty, value in exact.items()}

    remaining = size - sum(counts.values())
    if remaining:
        by_remainder = sorted(
            exact,
            key=lambda difficulty: (exact[difficulty] - counts[difficulty], mix[difficulty]),
            reverse=True,
        )
        for difficulty in by_remainder[:remaining]:
            counts[difficulty] += 1

    return counts


@dataclass(frozen=True)
class StratumFill:
    difficulty: Difficulty
    requested: int
    available: int

    @property
    def served(self) -> int:
        return min(self.requested, self.available)

    @property
    def starved(self) -> bool:
        return self.available < self.requested


@dataclass(frozen=True)
class MixOutcome:
    """What a slate build actually managed to serve, and whether that is degraded.

    The mix is a target, not a guarantee. With a thin corpus under free-tier quota
    this fires constantly, so the honest outcome is a first-class return value
    rather than an exception.
    """

    fills: tuple[StratumFill, ...]
    degraded: bool

    @property
    def starved_strata(self) -> tuple[Difficulty, ...]:
        return tuple(fill.difficulty for fill in self.fills if fill.starved)

    @property
    def total_served(self) -> int:
        return sum(fill.served for fill in self.fills)


def resolve_mix(
    size: int,
    tier: Difficulty,
    available: dict[Difficulty, int],
    *,
    was_degraded: bool,
    pool_low: int,
    pool_high: int,
) -> MixOutcome:
    """Decide what to serve when the pool cannot satisfy the mix.

    Policy (ADR-0006):

    1. Keep the mix honest — **never** silently backfill a starved stratum with
       the current difficulty. Serve a shorter page instead. Backfilling is the
       boring, invisible answer, and it destroys the upward slice that is the
       promotion signal while hiding pool starvation from us exactly when we most
       need to see it.
    2. The caller triggers an async fill for whatever `starved_strata` reports.
    3. Hysteresis: enter degraded below `pool_low`, leave it only above
       `pool_high`. Two thresholds deliberately — with one, the pool sits on the
       line, a card generates, degraded exits, the user consumes that card, and
       degraded re-enters. Every crossing re-triggers work.
    """

    requested = allocate(size, tier)
    fills = tuple(
        StratumFill(
            difficulty=difficulty,
            requested=count,
            available=available.get(difficulty, 0),
        )
        for difficulty, count in requested.items()
    )

    total_available = sum(available.get(fill.difficulty, 0) for fill in fills)
    degraded = total_available < pool_high if was_degraded else total_available < pool_low

    return MixOutcome(fills=fills, degraded=degraded)
