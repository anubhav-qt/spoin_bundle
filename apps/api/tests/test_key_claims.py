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


# --------------------------------------------------------------------------- #
# ADR-0078: topic leases and the shared reserve.
# --------------------------------------------------------------------------- #


def test_lease_takes_up_to_want_keys_and_the_reserve_is_what_is_left() -> None:
    registry = KeyClaimRegistry(5)
    lease = registry.lease_topic(3)

    assert len(lease.key_indices) == 3
    assert sorted(registry.reserve_keys()) == sorted(set(range(5)) - lease.key_indices)

    tight = registry.lease_topic(10)  # only 2 keys left
    assert len(tight.key_indices) == 2
    assert registry.reserve_keys() == []


@pytest.mark.asyncio
async def test_grow_and_shrink_a_lease(session: AsyncSession) -> None:
    registry = KeyClaimRegistry(6)
    lease = registry.lease_topic(2)
    assert len(lease.key_indices) == 2

    await registry.adjust_lease(lease, 4)
    assert len(lease.key_indices) == 4

    # A key a subtopic claim is mid-call on is never yanked; only unbound
    # surplus is returned.
    held = KeyClaim(lease=lease)
    registry.bind(held, min(lease.key_indices))
    await registry.adjust_lease(lease, 1)
    assert lease.key_indices == {held.key_index}  # only the mid-call key survives the shrink


@pytest.mark.asyncio
async def test_a_leased_claim_binds_only_from_its_own_lease(session: AsyncSession) -> None:
    governor = _governor(keys=4, ladder=_ladder(("model-a", 20, 5)))
    assert governor.claims is not None
    lease = governor.claims.lease_topic(1)
    (only_key,) = lease.key_indices

    claim = KeyClaim(lease=lease)
    for _ in range(3):
        result = await governor.acquire_for_claim_with_session(session, now=_NOW, claim=claim)
        assert result == (only_key, "model-a")
    assert claim.key_index == only_key


@pytest.mark.asyncio
async def test_a_leased_claim_borrows_the_reserve_before_its_own_weak_rung(
    session: AsyncSession,
) -> None:
    """The ADR-0078 ladder: own key's 3.7/3.6 -> a RESERVE key's 3.7/3.6 ->
    only then the own key's last ordinary rung. The borrow does not rebind the
    claim -- next call it is back on its home key."""

    governor = _governor(
        keys=3, ladder=_ladder(("model-a", 20, 5), ("model-b", 20, 5), ("model-c", 20, 5))
    )
    assert governor.claims is not None
    lease = governor.claims.lease_topic(1)
    (home,) = lease.key_indices
    claim = KeyClaim(lease=lease)
    governor.claims.bind(claim, home)
    await _drain(governor, session, home, "model-a", 20)
    await _drain(governor, session, home, "model-b", 20)

    result = await governor.acquire_for_claim_with_session(session, now=_NOW, claim=claim)

    assert isinstance(result, tuple)
    assert result[0] != home
    assert result[0] in governor.claims.reserve_keys()  # a borrow leaves the key in the reserve
    assert result[1] == "model-a"  # a reserve key's PREFERRED rung, not home's model-c
    assert claim.key_index == home  # borrow, not move


@pytest.mark.asyncio
async def test_a_leased_claim_never_borrows_another_topics_key(session: AsyncSession) -> None:
    governor = _governor(keys=3, ladder=_ladder(("model-a", 20, 5), ("model-b", 20, 5)))
    assert governor.claims is not None
    mine = governor.claims.lease_topic(1)
    theirs = governor.claims.lease_topic(1)
    (my_key,) = mine.key_indices
    (their_key,) = theirs.key_indices
    (reserve_key,) = governor.claims.reserve_keys()

    claim = KeyClaim(lease=mine)
    governor.claims.bind(claim, my_key)
    await _drain(governor, session, my_key, "model-a", 20)
    await _drain(governor, session, my_key, "model-b", 20)

    result = await governor.acquire_for_claim_with_session(session, now=_NOW, claim=claim)

    assert result == (reserve_key, "model-a")
    assert result[0] != their_key


@pytest.mark.asyncio
async def test_an_unbound_leased_claim_waits_when_its_lease_is_full(session: AsyncSession) -> None:
    """A subtopic branch with no key yet does NOT borrow a reserve key as its
    home -- it waits for a sibling in the same topic to release one."""

    governor = _governor(keys=3, ladder=_ladder(("model-a", 20, 5)))
    assert governor.claims is not None
    lease = governor.claims.lease_topic(1)
    (only_key,) = lease.key_indices

    sibling = KeyClaim(lease=lease)
    governor.claims.bind(sibling, only_key)

    newcomer = KeyClaim(lease=lease)
    result = await governor.acquire_for_claim_with_session(session, now=_NOW, claim=newcomer)

    assert isinstance(result, _ClaimWait)
    assert newcomer.key_index is None
    assert result.other_claims == 1  # the sibling holding the lease's only key


def test_lease_follows_the_cold_first_order_it_is_given() -> None:
    """ADR-0078 + ADR-0065: a lease is held for the whole day's worth of a
    topic's passes, so leasing key 0 first every time would burn the low
    indices down and leave the rest -- the reserve included -- cold. `prefer`
    is the ledger-derived least-spent-first order; the lease follows it and
    skips whatever is already taken."""

    registry = KeyClaimRegistry(5)
    first = registry.lease_topic(2, prefer=[3, 4, 0, 1, 2])
    assert first.key_indices == {3, 4}

    second = registry.lease_topic(2, prefer=[3, 4, 0, 1, 2])
    assert second.key_indices == {0, 1}  # 3 and 4 gone, next-coldest taken


@pytest.mark.asyncio
async def test_key_spend_today_sums_a_keys_cells_and_drives_cold_first_leasing(
    session: AsyncSession,
) -> None:
    from spoin.generation.quota import key_spend_today

    governor = _governor(keys=4, ladder=_ladder(("model-a", 100, 100), ("model-b", 100, 100)))
    assert governor.claims is not None
    await _drain(governor, session, 0, "model-a", 30)
    await _drain(governor, session, 0, "model-b", 20)  # key 0: 50 across both cells
    await _drain(governor, session, 1, "model-a", 5)  # key 1: 5

    spent = await key_spend_today(session, key_count=4, now=_NOW)
    assert spent == {0: 50, 1: 5}  # keys 2, 3 untouched -> absent -> 0

    order = sorted(range(4), key=lambda k: (spent.get(k, 0), k))
    assert order == [2, 3, 1, 0]

    lease = governor.claims.lease_topic(2, prefer=order)
    assert lease.key_indices == {2, 3}  # the two coldest, not 0 and 1


@pytest.mark.asyncio
async def test_releasing_a_topic_lease_hands_every_key_back(session: AsyncSession) -> None:
    registry = KeyClaimRegistry(4)
    lease = registry.lease_topic(3)
    claim = KeyClaim(lease=lease)
    registry.bind(claim, next(iter(lease.key_indices)))

    await registry.release_topic(lease)

    assert registry.reserve_keys() == [0, 1, 2, 3]
    assert lease.key_indices == set()
    assert claim.key_index is None


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
