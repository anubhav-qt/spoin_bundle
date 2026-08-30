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

    assert isinstance(result, float)
    assert result > 0


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
        await governor.acquire_for_claim_with_session(session, now=_NOW, claim=waiter), float
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
