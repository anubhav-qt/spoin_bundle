"""ADR-0074: one key per subtopic group, and the own-key-first ladder.

Same posture as `test_quota_governor.py` -- the real Postgres `session` fixture,
because what is under test is a decision made FROM the ledger, and mocking the
ledger would only ever prove the mock agrees with itself. Nothing sleeps: every
case drives `now` by hand.

The property these tests exist to protect is not "the right cell was picked" but
**one caller per key**. That is what makes an rpm violation structurally
impossible rather than merely counted, and it is invisible in a passing
generation run right up until the day it is not true any more.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from spoin.generation.quota import (
    KeyClaim,
    KeyClaimRegistry,
    LadderRung,
    QuotaGovernor,
    _ClaimWait,
    _day_start,
)


def _ladder(*rungs: tuple[str, int, int]) -> list[LadderRung]:
    return [LadderRung(model=model, rpd=rpd, rpm=rpm) for model, rpd, rpm in rungs]


def _governor(*, keys: int, ladder: list[LadderRung], reserve: int = 0) -> QuotaGovernor:
    return QuotaGovernor(
        key_count=keys, ladder=ladder, reserve_rungs=reserve, claims=KeyClaimRegistry(keys)
    )


_NOW = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)


async def _drain(
    governor: QuotaGovernor, session: AsyncSession, key_index: int, model: str, count: int
) -> None:
    """Spend `count` of a cell's daily budget without going through the ladder."""

    day = _day_start(_NOW)
    ledger = await governor._ledger_row(session, day, key_index, model)
    ledger.requests_spent += count
    await session.flush()


@pytest.mark.asyncio
async def test_a_claim_binds_to_one_key_and_stays_on_it(session: AsyncSession) -> None:
    """The first call binds the claim; later calls come back to the same key
    even though every other key is emptier by then."""

    governor = _governor(keys=3, ladder=_ladder(("model-a", 20, 5)))
    claim = KeyClaim()
    assert claim.key_index is None

    granted = [
        await governor.acquire_for_claim_with_session(session, now=_NOW, claim=claim)
        for _ in range(3)
    ]

    assert all(isinstance(result, tuple) for result in granted)
    assert {result[0] for result in granted if isinstance(result, tuple)} == {claim.key_index}


@pytest.mark.asyncio
async def test_own_keys_second_rung_beats_another_keys_first(session: AsyncSession) -> None:
    """The deliberate inversion of ADR-0028's model-major order, on the real
    shape: three ordinary rungs, so model-a and model-b are both PREFERRED and
    model-c is the deferred one. Key 0 has no model-a left, and model-b on key 0
    beats model-a on the free key 1 -- staying on the claimed key is the point
    of claiming it.

    Note this only holds for a preferred rung. With a two-rung ladder, model-b
    would BE the deferred rung and the free key would rightly win instead; that
    case is `test_own_keys_last_ordinary_rung_only_after_free_keys_are_checked`.
    """

    governor = _governor(
        keys=2,
        ladder=_ladder(("model-a", 20, 5), ("model-b", 20, 5), ("model-c", 20, 5)),
    )
    claim = KeyClaim()
    assert governor.claims is not None
    governor.claims.bind(claim, 0)
    await _drain(governor, session, 0, "model-a", 20)

    assert await governor.acquire_for_claim_with_session(session, now=_NOW, claim=claim) == (
        0,
        "model-b",
    )


@pytest.mark.asyncio
async def test_the_claim_moves_when_its_key_runs_out_of_preferred_rungs(
    session: AsyncSession,
) -> None:
    """Step 3: with model-c the only rung left on key 0, a FREE key that still
    has a preferred rung wins -- otherwise a group strands itself on a dying key
    while 32 healthy ones sit there."""

    governor = _governor(
        keys=2,
        ladder=_ladder(("model-a", 20, 5), ("model-b", 20, 5), ("model-c", 20, 5)),
    )
    claim = KeyClaim()
    assert governor.claims is not None
    governor.claims.bind(claim, 0)
    await _drain(governor, session, 0, "model-a", 20)
    await _drain(governor, session, 0, "model-b", 20)

    result = await governor.acquire_for_claim_with_session(session, now=_NOW, claim=claim)

    assert result == (1, "model-a")
    assert claim.key_index == 1
    assert governor.claims.is_free(0)


@pytest.mark.asyncio
async def test_own_keys_last_ordinary_rung_only_after_free_keys_are_checked(
    session: AsyncSession,
) -> None:
    """The mirror of the test above: when NO key is free, the claim falls to its
    own last ordinary rung rather than waiting or borrowing."""

    governor = _governor(
        keys=2,
        ladder=_ladder(("model-a", 20, 5), ("model-b", 20, 5), ("model-c", 20, 5)),
    )
    assert governor.claims is not None
    mine, theirs = KeyClaim(), KeyClaim()
    governor.claims.bind(mine, 0)
    governor.claims.bind(theirs, 1)
    await _drain(governor, session, 0, "model-a", 20)
    await _drain(governor, session, 0, "model-b", 20)

    assert await governor.acquire_for_claim_with_session(session, now=_NOW, claim=mine) == (
        0,
        "model-c",
    )


@pytest.mark.asyncio
async def test_a_busy_grid_waits_instead_of_spending_the_reserve(session: AsyncSession) -> None:
    """The distinction the reserve exists for. Every ordinary cell on MY key is
    spent and the only other key is claimed by someone else -- but that key has
    full daily budget, so the day is BUSY, not gone. The answer is a wait, not
    the weakest model."""

    governor = _governor(
        keys=2, ladder=_ladder(("model-a", 20, 5), ("model-reserve", 20, 5)), reserve=1
    )
    assert governor.claims is not None
    mine, theirs = KeyClaim(), KeyClaim()
    governor.claims.bind(mine, 0)
    governor.claims.bind(theirs, 1)
    await _drain(governor, session, 0, "model-a", 20)

    result = await governor.acquire_for_claim_with_session(session, now=_NOW, claim=mine)

    assert isinstance(result, _ClaimWait)
    assert result.seconds > 0
    # The reason, not just the duration: with the other key held and nothing
    # throttled, waiting on a RELEASE is the only thing that can help.
    assert result.other_claims == 1
    assert result.free_keys == 0
    assert result.throttled_cells == 0
    assert result.waiting_on_a_key


@pytest.mark.asyncio
async def test_the_reserve_opens_once_no_key_has_ordinary_daily_room(
    session: AsyncSession,
) -> None:
    """The other half: the same claim, the same held key, but now the other
    key's ordinary budget is gone too. Nothing to wait for, so the reserve is
    finally right."""

    governor = _governor(
        keys=2, ladder=_ladder(("model-a", 20, 5), ("model-reserve", 20, 5)), reserve=1
    )
    assert governor.claims is not None
    mine, theirs = KeyClaim(), KeyClaim()
    governor.claims.bind(mine, 0)
    governor.claims.bind(theirs, 1)
    await _drain(governor, session, 0, "model-a", 20)
    await _drain(governor, session, 1, "model-a", 20)

    assert await governor.acquire_for_claim_with_session(session, now=_NOW, claim=mine) == (
        0,
        "model-reserve",
    )


@pytest.mark.asyncio
async def test_two_claims_never_land_on_the_same_key(session: AsyncSession) -> None:
    """The whole guarantee, stated directly. Two units of work, two keys, and
    the second never gets handed the first one's key."""

    governor = _governor(keys=2, ladder=_ladder(("model-a", 20, 5)))
    first, second = KeyClaim(), KeyClaim()

    granted_first = await governor.acquire_for_claim_with_session(session, now=_NOW, claim=first)
    granted_second = await governor.acquire_for_claim_with_session(session, now=_NOW, claim=second)

    assert isinstance(granted_first, tuple)
    assert isinstance(granted_second, tuple)
    assert granted_first[0] != granted_second[0]


@pytest.mark.asyncio
async def test_releasing_a_claim_hands_its_key_back(session: AsyncSession) -> None:
    governor = _governor(keys=1, ladder=_ladder(("model-a", 20, 5)))
    assert governor.claims is not None
    holder, waiter = KeyClaim(), KeyClaim()

    assert isinstance(
        await governor.acquire_for_claim_with_session(session, now=_NOW, claim=holder), tuple
    )
    assert isinstance(
        await governor.acquire_for_claim_with_session(session, now=_NOW, claim=waiter), _ClaimWait
    )

    await governor.claims.release(holder)

    assert await governor.acquire_for_claim_with_session(session, now=_NOW, claim=waiter) == (
        0,
        "model-a",
    )


def test_a_ladder_too_short_for_a_reserve_simply_has_none() -> None:
    """A single-rung ladder that kept its reserve would hold back its only
    model and refuse every call while sitting on full quota."""

    governor = QuotaGovernor(key_count=1, ladder=_ladder(("only-model", 20, 5)), reserve_rungs=1)

    assert governor.reserve_rungs == 0


def test_a_negative_reserve_is_a_configuration_error() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        QuotaGovernor(key_count=1, ladder=_ladder(("model-a", 20, 5)), reserve_rungs=-1)


@pytest.mark.asyncio
async def test_an_unclaimed_acquire_is_unchanged(session: AsyncSession) -> None:
    """ADR-0074 adds a path, it does not replace one. Topic matching from the
    API process, and the recovery probe, still acquire without a claim and still
    get ADR-0028's model-major, least-spent-key order."""

    governor = _governor(keys=2, ladder=_ladder(("model-a", 1, 5), ("model-b", 20, 5)))

    first = await governor.acquire_with_session(session, now=_NOW)
    second = await governor.acquire_with_session(session, now=_NOW)
    third = await governor.acquire_with_session(session, now=_NOW)

    assert {first, second} == {(0, "model-a"), (1, "model-a")}
    assert third[1] == "model-b"


@pytest.mark.asyncio
async def test_a_throttled_wait_is_not_reported_as_a_contended_one(
    session: AsyncSession,
) -> None:
    """Contention and throttling are different facts and must not share a
    message. Here the pool is the OPPOSITE of busy -- one key, unclaimed, and
    the reason there is no cell is that its minute is full.

    The log line this pins used to assert "every key is claimed" on every
    fall-through, which sent the reader looking for a key shortage when the
    real answer was to wait ~40 seconds. Same shape as CLAUDE.md's "a failed
    outcome and a rejected outcome are never the same number".
    """

    governor = _governor(keys=1, ladder=_ladder(("model-a", 20, 1)))
    claim = KeyClaim()

    assert isinstance(
        await governor.acquire_for_claim_with_session(session, now=_NOW, claim=claim), tuple
    )
    result = await governor.acquire_for_claim_with_session(session, now=_NOW, claim=claim)

    assert isinstance(result, _ClaimWait)
    # ONE cell, counted once, even though the scan visits it several times.
    assert result.throttled_cells == 1
    # Nothing is contending: the only key is this claim's own, which is neither
    # something to wait for nor somewhere to move to.
    assert result.other_claims == 0
    assert result.free_keys == 0
    assert not result.waiting_on_a_key


# --- ADR-0082: key boxes -----------------------------------------------------
#
# The box tests protect a second property on top of "one caller per key": a
# topic's calls never leave its box. That is what bounds total in-flight work at
# `max_concurrent_topics * box_size` regardless of how many topics are queued --
# the bound ADR-0078 lost by letting a spent claim reach a shared reserve.


@pytest.mark.asyncio
async def test_a_boxed_claim_never_binds_outside_its_box(session: AsyncSession) -> None:
    governor = _governor(keys=4, ladder=_ladder(("model-a", 20, 5)))
    assert governor.claims is not None
    box = governor.claims.lease_box(2)
    claim = KeyClaim(box=box)

    granted = await governor.acquire_for_claim_with_session(session, now=_NOW, claim=claim)

    assert isinstance(granted, tuple)
    assert granted[0] in box.key_indices


@pytest.mark.asyncio
async def test_a_spent_boxed_key_moves_within_the_box_not_outside_it(
    session: AsyncSession,
) -> None:
    """ADR-0074's step 2 still applies -- a claim whose key is spent moves to a
    fresher one -- but "fresher one" means inside the box. The two keys outside
    it are completely untouched and still refused."""

    governor = _governor(keys=4, ladder=_ladder(("model-a", 20, 5)))
    assert governor.claims is not None
    box = governor.claims.lease_box(2, prefer=[0, 1])
    claim = KeyClaim(box=box)

    first = await governor.acquire_for_claim_with_session(session, now=_NOW, claim=claim)
    assert isinstance(first, tuple)
    await _drain(governor, session, first[0], "model-a", 20)

    second = await governor.acquire_for_claim_with_session(session, now=_NOW, claim=claim)

    assert isinstance(second, tuple)
    assert second[0] != first[0]
    assert second[0] in {0, 1}


@pytest.mark.asyncio
async def test_two_boxes_never_share_a_key(session: AsyncSession) -> None:
    governor = _governor(keys=4, ladder=_ladder(("model-a", 20, 5)))
    assert governor.claims is not None

    first = governor.claims.lease_box(2)
    second = governor.claims.lease_box(2)

    assert len(first.key_indices) == 2
    assert not first.key_indices & second.key_indices


@pytest.mark.asyncio
async def test_a_box_takes_what_is_left_when_the_pool_is_short(session: AsyncSession) -> None:
    """A short box is not an error (`lease_box`): a topic with fewer keys than
    it asked for still generates, where refusing to start would idle them."""

    governor = _governor(keys=3, ladder=_ladder(("model-a", 20, 5)))
    assert governor.claims is not None

    governor.claims.lease_box(2)
    second = governor.claims.lease_box(2)

    assert len(second.key_indices) == 1


@pytest.mark.asyncio
async def test_a_box_whose_day_is_spent_reaches_the_reserve_rung(session: AsyncSession) -> None:
    """The daily-room test is scoped to the box too. With the box's own keys
    exhausted on the ordinary rung, this claim escalates to the reserve even
    though the key OUTSIDE the box is completely fresh -- waiting on budget it
    can never be given is not contention, it is a hang."""

    governor = _governor(keys=2, ladder=_ladder(("model-a", 20, 5), ("reserve", 20, 5)), reserve=1)
    assert governor.claims is not None
    box = governor.claims.lease_box(1, prefer=[0])
    await _drain(governor, session, 0, "model-a", 20)

    granted = await governor.acquire_for_claim_with_session(
        session, now=_NOW, claim=KeyClaim(box=box)
    )

    assert granted == (0, "reserve")


@pytest.mark.asyncio
async def test_a_boxed_wait_counts_only_its_own_topics_keys(session: AsyncSession) -> None:
    """The wait line a boxed claim logs is about ITS topic. A sibling group
    holds the box's only other key; the two keys outside the box are neither
    something to wait for nor somewhere to move to, so they are not counted."""

    governor = _governor(keys=4, ladder=_ladder(("model-a", 20, 1)))
    assert governor.claims is not None
    box = governor.claims.lease_box(2, prefer=[0, 1])
    sibling, claim = KeyClaim(box=box), KeyClaim(box=box)

    assert isinstance(
        await governor.acquire_for_claim_with_session(session, now=_NOW, claim=sibling), tuple
    )
    assert isinstance(
        await governor.acquire_for_claim_with_session(session, now=_NOW, claim=claim), tuple
    )
    result = await governor.acquire_for_claim_with_session(session, now=_NOW, claim=claim)

    assert isinstance(result, _ClaimWait)
    assert result.free_keys == 0
    assert result.other_claims == 1


@pytest.mark.asyncio
async def test_releasing_a_box_returns_its_keys_and_drops_its_claims(
    session: AsyncSession,
) -> None:
    governor = _governor(keys=2, ladder=_ladder(("model-a", 20, 5)))
    assert governor.claims is not None
    box = governor.claims.lease_box(2)
    claim = KeyClaim(box=box)
    assert isinstance(
        await governor.acquire_for_claim_with_session(session, now=_NOW, claim=claim), tuple
    )

    await governor.claims.release_box(box)

    assert claim.key_index is None
    assert governor.claims.free_keys() == [0, 1]
    # And the keys are boxable again -- a released box leaves nothing behind.
    assert len(governor.claims.lease_box(2).key_indices) == 2


@pytest.mark.asyncio
async def test_an_unboxed_claim_still_sees_the_whole_pool(session: AsyncSession) -> None:
    """ADR-0082 adds a scope, it does not replace one. A claim with no box --
    the `fake` backend, a CLI run against a keyless generator -- keeps ADR-0074's
    whole-pool ladder."""

    governor = _governor(keys=2, ladder=_ladder(("model-a", 20, 5)))
    claim = KeyClaim()

    first = await governor.acquire_for_claim_with_session(session, now=_NOW, claim=claim)
    assert isinstance(first, tuple)
    await _drain(governor, session, first[0], "model-a", 20)
    second = await governor.acquire_for_claim_with_session(session, now=_NOW, claim=claim)

    assert isinstance(second, tuple)
    assert second[0] != first[0]
