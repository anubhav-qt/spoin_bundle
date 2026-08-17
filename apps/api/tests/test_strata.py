"""The difficulty mix is the one thing ADR-0010 promises is *exact*.

These tests exist because "80% beginner" being approximately true is the failure
mode the stratified design was chosen to eliminate. If they go green while the mix
drifts, the whole argument for the extra complexity is gone.
"""

from __future__ import annotations

import pytest

from spoin.core.config import DIFFICULTY_MIX
from spoin.domain.enums import Difficulty
from spoin.feed.strata import allocate, resolve_mix


@pytest.mark.parametrize("size", [1, 5, 7, 10, 25, 33, 50])
@pytest.mark.parametrize("tier", list(Difficulty))
def test_allocation_always_sums_exactly(size: int, tier: Difficulty) -> None:
    """Naive rounding loses or gains a slot. Largest-remainder must not."""

    counts = allocate(size, tier)
    assert sum(counts.values()) == size


@pytest.mark.parametrize("tier", list(Difficulty))
def test_allocation_only_uses_configured_tiers(tier: Difficulty) -> None:
    assert set(allocate(25, tier)) == set(DIFFICULTY_MIX[tier])


def test_beginner_mix_is_exactly_eighty_twenty() -> None:
    counts = allocate(25, Difficulty.BEGINNER)
    assert counts[Difficulty.BEGINNER] == 20
    assert counts[Difficulty.INTERMEDIATE] == 5


def test_upward_slice_survives_small_pages() -> None:
    """The upward slice is the promotion signal, not variety garnish.

    If it rounds away on every realistic page size, we never collect the evidence
    that a user is ready to move up.
    """

    counts = allocate(10, Difficulty.BEGINNER)
    assert counts[Difficulty.INTERMEDIATE] >= 1


def test_starved_stratum_is_never_backfilled() -> None:
    """Serve short, never wrong.

    Backfilling a starved stratum with the current difficulty is invisible to the
    user and destroys both the mix and our ability to see pool starvation.
    """

    outcome = resolve_mix(
        10,
        Difficulty.BEGINNER,
        {Difficulty.BEGINNER: 8, Difficulty.INTERMEDIATE: 0},
        was_degraded=False,
        pool_low=5,
        pool_high=15,
    )

    served = {fill.difficulty: fill.served for fill in outcome.fills}
    assert served[Difficulty.BEGINNER] == 8, "must not exceed what exists"
    assert served[Difficulty.INTERMEDIATE] == 0, "must not be backfilled from beginner"
    assert outcome.total_served == 8, "a short page, not a full one made of the wrong cards"
    assert Difficulty.INTERMEDIATE in outcome.starved_strata


class TestHysteresis:
    """Two thresholds, deliberately (ADR-0006 §3).

    With one threshold the system flaps: the pool sits on the line, a card
    generates, degraded exits, the user consumes that card, degraded re-enters —
    and every crossing re-triggers work.
    """

    @staticmethod
    def _outcome(available: int, *, was_degraded: bool) -> bool:
        return resolve_mix(
            10,
            Difficulty.BEGINNER,
            {Difficulty.BEGINNER: available, Difficulty.INTERMEDIATE: 0},
            was_degraded=was_degraded,
            pool_low=5,
            pool_high=15,
        ).degraded

    def test_enters_below_pool_low(self) -> None:
        assert self._outcome(4, was_degraded=False) is True

    def test_does_not_enter_between_thresholds(self) -> None:
        assert self._outcome(10, was_degraded=False) is False

    def test_stays_degraded_between_thresholds(self) -> None:
        """The gap is the entire point: recovering at 6 would immediately flap."""

        assert self._outcome(10, was_degraded=True) is True

    def test_exits_only_above_pool_high(self) -> None:
        assert self._outcome(16, was_degraded=True) is False
