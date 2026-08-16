"""Interleave plan: weighted round-robin with deficit counters."""

from __future__ import annotations

from collections import Counter
from itertools import groupby, pairwise
from uuid import UUID, uuid4

from slocho.feed.interleave import build_plan, filter_key

A = UUID("00000000-0000-0000-0000-0000000000aa")
B = UUID("00000000-0000-0000-0000-0000000000bb")
C = UUID("00000000-0000-0000-0000-0000000000cc")


def test_equal_affinity_alternates() -> None:
    plan = build_plan({A: 1.0, B: 1.0}, 10)
    counts = Counter(plan)
    assert counts[A] == counts[B] == 5


def test_double_affinity_gets_double_slots() -> None:
    plan = build_plan({A: 2.0, B: 1.0}, 30)
    counts = Counter(plan)
    assert counts[A] == 2 * counts[B]


def test_slots_are_spread_not_clumped() -> None:
    """A topic with 2x affinity gets 2x the slots *spread evenly*.

    Clumping would give the same totals while making the feed feel like reading one
    topic and then another — which is the thing the interleave exists to prevent.
    """

    plan = build_plan({A: 2.0, B: 1.0}, 30)
    longest_run = max_run = 1
    for previous, current in pairwise(plan):
        max_run = max_run + 1 if current == previous else 1
        longest_run = max(longest_run, max_run)

    assert longest_run <= 2


def test_run_length_groups_slots_without_changing_share() -> None:
    """Runs change the granularity of alternation, never the allocation.

    This is what lets the client put a heading above each topic's cards. At
    run_length=1 a heading would appear before every single card.
    """

    affinities = {A: 2.0, B: 1.0}
    grouped = build_plan(affinities, 30, run_length=3)
    counts = Counter(grouped)

    assert len(grouped) == 30

    # Slots are awarded a whole run at a time, so an exact 2:1 split is only
    # reachable when the run count divides evenly — 30 slots at run 3 is 10 runs,
    # and 2:1 wants 6.67 of them. The share stays proportional to within one run,
    # which is the tightest guarantee grouping can make.
    assert abs(counts[A] - 2 * counts[B]) <= 3


def test_run_length_actually_produces_runs() -> None:
    plan = build_plan({A: 1.0, B: 1.0}, 12, run_length=3)

    runs = [len(list(group)) for _, group in groupby(plan)]
    assert max(runs) >= 3, "a topic should hold the rail for several cards"


def test_run_length_one_is_the_original_behaviour() -> None:
    """ADR-0010's 'spread evenly rather than clumped' must remain reachable."""

    plan = build_plan({A: 1.0, B: 1.0}, 10, run_length=1)
    assert all(a != b for a, b in pairwise(plan))


def test_plan_never_exceeds_requested_size() -> None:
    """A run that would overshoot is truncated, not appended whole."""

    assert len(build_plan({A: 1.0, B: 1.0}, 10, run_length=4)) == 10
    assert len(build_plan({A: 1.0}, 7, run_length=5)) == 7


def test_deterministic() -> None:
    """Same inputs, same plan — so a surprising feed is reproducible from a report."""

    affinities = {A: 1.5, B: 1.0, C: 0.5}
    assert build_plan(affinities, 20) == build_plan(affinities, 20)


def test_no_topics_is_an_ordinary_state() -> None:
    assert build_plan({}, 50) == []


def test_zero_affinity_topics_are_excluded() -> None:
    assert set(build_plan({A: 1.0, B: 0.0}, 10)) == {A}


def test_filter_key_is_order_independent() -> None:
    """Filtering to [A, B] and [B, A] is the same filter; regenerating the plan for
    the second would reset the user's position for no reason."""

    assert filter_key([A, B]) == filter_key([B, A])
    assert filter_key(None) == filter_key([]) == ""
    assert filter_key([A]) != filter_key([A, uuid4()])
