"""Session-scoped topic shares: squash, clamp-and-redistribute, fingerprint (ADR-0055)."""

from __future__ import annotations

import math
from uuid import UUID, uuid4

import pytest

from spoin.core.config import Settings
from spoin.feed.session_profile import (
    MIN_RAW_WEIGHT,
    clamp_shares,
    raw_weight,
    share_fingerprint,
    squash,
)

A = UUID("00000000-0000-0000-0000-0000000000aa")
B = UUID("00000000-0000-0000-0000-0000000000bb")
C = UUID("00000000-0000-0000-0000-0000000000cc")
D = UUID("00000000-0000-0000-0000-0000000000dd")

LO = 0.05
HI = 0.50


@pytest.fixture
def settings() -> Settings:
    return Settings()


# ---------------------------------------------------------------------- squash --
def test_squash_is_zero_at_zero() -> None:
    assert squash(0.0, 10.0) == 0.0


def test_squash_reaches_half_at_k() -> None:
    assert squash(10.0, 10.0) == pytest.approx(0.5)
    assert squash(-10.0, 10.0) == pytest.approx(-0.5)


def test_squash_is_bounded_and_monotonic() -> None:
    previous = -1.0
    for score in range(-1000, 1000, 7):
        value = squash(float(score), 10.0)
        assert -1.0 < value < 1.0
        assert value > previous
        previous = value


# ------------------------------------------------------------------ raw_weight --
def test_no_signal_is_the_uniform_baseline(settings: Settings) -> None:
    """The whole point of the 30-minute reset: a fresh session ranks nothing."""

    assert raw_weight(0.0, settings) == pytest.approx(1.0)


def test_engagement_raises_and_skipping_lowers(settings: Settings) -> None:
    assert raw_weight(20.0, settings) > raw_weight(0.0, settings)
    assert raw_weight(-20.0, settings) < raw_weight(0.0, settings)


def test_weight_never_reaches_zero(settings: Settings) -> None:
    """`build_plan` drops non-positive weights, and a topic must never vanish
    outright from one bad session -- that is what the floor share is for."""

    assert raw_weight(-1e9, settings) >= MIN_RAW_WEIGHT


# ---------------------------------------------------------------- clamp_shares --
def test_empty_input() -> None:
    assert clamp_shares({}, lo=LO, hi=HI) == {}


def test_shares_sum_to_one() -> None:
    shares = clamp_shares({A: 3.0, B: 1.0, C: 1.0, D: 0.5}, lo=LO, hi=HI)
    assert sum(shares.values()) == pytest.approx(1.0)


def test_bounds_are_respected() -> None:
    shares = clamp_shares({A: 500.0, B: 1.0, C: 0.01, D: 0.01}, lo=LO, hi=HI)
    assert sum(shares.values()) == pytest.approx(1.0)
    for share in shares.values():
        assert LO - 1e-9 <= share <= HI + 1e-9


def test_ordering_is_preserved() -> None:
    shares = clamp_shares({A: 8.0, B: 4.0, C: 2.0, D: 1.0}, lo=LO, hi=HI)
    assert shares[A] >= shares[B] >= shares[C] >= shares[D]


def test_dominant_topic_is_capped_at_the_ceiling() -> None:
    shares = clamp_shares({A: 1000.0, B: 1.0, C: 1.0, D: 1.0}, lo=LO, hi=HI)
    assert shares[A] == pytest.approx(HI)


def test_ignored_topic_keeps_the_floor() -> None:
    shares = clamp_shares({A: 100.0, B: 100.0, C: 100.0, D: 0.0}, lo=LO, hi=HI)
    assert shares[D] == pytest.approx(LO)


def test_equal_weights_are_uniform() -> None:
    shares = clamp_shares(dict.fromkeys([A, B, C, D], 2.0), lo=LO, hi=HI)
    for share in shares.values():
        assert share == pytest.approx(0.25)


def test_all_zero_weights_fall_back_to_uniform() -> None:
    shares = clamp_shares(dict.fromkeys([A, B, C], 0.0), lo=LO, hi=HI)
    for share in shares.values():
        assert share == pytest.approx(1 / 3)


def test_single_topic_takes_the_whole_feed() -> None:
    """A 50% ceiling on a lone topic is meaningless -- the other half of the feed
    would have nowhere to come from."""

    assert clamp_shares({A: 4.0}, lo=LO, hi=HI) == {A: pytest.approx(1.0)}


def test_two_topics_both_pin_at_the_ceiling() -> None:
    shares = clamp_shares({A: 99.0, B: 1.0}, lo=LO, hi=HI)
    assert shares[A] == pytest.approx(0.5)
    assert shares[B] == pytest.approx(0.5)


def test_floor_degrades_when_arithmetically_impossible() -> None:
    """25 topics cannot each hold 5% -- that sums to 125%. The floor falls back to
    `1/n`, which is the tightest bound that is always feasible."""

    topics = {uuid4(): 1.0 for _ in range(25)}
    shares = clamp_shares(topics, lo=LO, hi=HI)
    assert sum(shares.values()) == pytest.approx(1.0)
    for share in shares.values():
        assert share == pytest.approx(1 / 25)


def test_negative_weights_are_floored_not_subtracted() -> None:
    shares = clamp_shares({A: 5.0, B: -3.0, C: 1.0}, lo=LO, hi=HI)
    assert sum(shares.values()) == pytest.approx(1.0)
    assert shares[B] == pytest.approx(LO)


def test_wide_spread_still_sums_to_one() -> None:
    """The case that broke the pin-and-redistribute approach: a spread wide enough
    that some topics hit the ceiling while others hit the floor in the same pass."""

    topics = {uuid4(): float(2**i) for i in range(12)}
    shares = clamp_shares(topics, lo=LO, hi=HI)
    assert sum(shares.values()) == pytest.approx(1.0)
    for share in shares.values():
        assert LO - 1e-9 <= share <= HI + 1e-9


def test_two_topics_over_ceiling_do_not_over_allocate() -> None:
    """Two topics both above the ceiling and the rest below the floor cannot all be
    pinned to their bounds -- that commits more than the whole feed."""

    topics = {uuid4(): weight for weight in (48.0, 47.0, 0.5, 0.5, 0.5, 0.5)}
    shares = clamp_shares(topics, lo=LO, hi=HI)
    assert sum(shares.values()) == pytest.approx(1.0)
    for share in shares.values():
        assert LO - 1e-9 <= share <= HI + 1e-9


def test_no_share_is_nan_for_extreme_spreads() -> None:
    shares = clamp_shares({A: 1e18, B: 1e-18, C: 0.0}, lo=LO, hi=HI)
    for share in shares.values():
        assert not math.isnan(share)


# ----------------------------------------------------------- share_fingerprint --
def test_fingerprint_is_stable_for_identical_shares() -> None:
    shares = {A: 0.5, B: 0.3, C: 0.2}
    assert share_fingerprint(shares, 0.05) == share_fingerprint(dict(shares), 0.05)


def test_fingerprint_ignores_key_order() -> None:
    assert share_fingerprint({A: 0.6, B: 0.4}, 0.05) == share_fingerprint({B: 0.4, A: 0.6}, 0.05)


def test_fingerprint_absorbs_drift_within_a_bucket() -> None:
    """Every event nudges the score. If a nudge that small reordered the feed, the
    plan would rebuild on every ingest."""

    assert share_fingerprint({A: 0.500, B: 0.500}, 0.05) == share_fingerprint(
        {A: 0.505, B: 0.495}, 0.05
    )


def test_fingerprint_changes_across_a_bucket_boundary() -> None:
    assert share_fingerprint({A: 0.50, B: 0.50}, 0.05) != share_fingerprint(
        {A: 0.60, B: 0.40}, 0.05
    )


def test_fingerprint_changes_with_the_topic_set() -> None:
    assert share_fingerprint({A: 0.5, B: 0.5}, 0.05) != share_fingerprint({A: 0.5, C: 0.5}, 0.05)
