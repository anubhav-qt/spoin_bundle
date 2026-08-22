"""Feed serving against a real database.

ADR-0010 is explicit that deferred-card cycling "is genuinely fiddly and needs real
test coverage. A bug here shows as 'I keep seeing the same cards', which is the most
damaging feed bug there is." So it is covered here, first.
"""

from __future__ import annotations

import random
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spoin.core.config import Settings
from spoin.domain.enums import Difficulty, EngagementKind, SeenState
from spoin.domain.models import Card, UserCardState, UserTopicCycle, UserTopicDifficultyProgress
from spoin.engagement.service import EngagementService, IncomingEvent
from spoin.feed.service import FeedService

pytestmark = pytest.mark.asyncio

RNG = random.Random(1234)


async def _seed_read_fraction(
    session: AsyncSession,
    user_id: Any,
    topic_id: Any,
    difficulty: Difficulty,
    *,
    seen: int,
    total: int,
) -> None:
    """Directly seeds the dynamic-mix ramp's input aggregate, bypassing the
    engagement ingest pipeline — these tests care about what `build_slate`
    does with a given read fraction, not how that fraction gets produced."""

    session.add(
        UserTopicDifficultyProgress(
            user_id=user_id,
            topic_id=topic_id,
            difficulty=difficulty,
            seen_count=seen,
            total_count=total,
        )
    )
    await session.flush()


async def test_fresh_tier_is_entirely_the_current_difficulty(
    session: AsyncSession, corpus: dict[str, Any], settings: Settings
) -> None:
    """Before the ramp starts (0% of this difficulty read), the mix is 100%
    the current tier — no promotion-signal cards yet, per the dynamic mix
    ramp (feed/strata.py `dynamic_mix`)."""

    service = FeedService(session, Settings(slate_size=10, rank_epsilon=0.0))
    slate = await service.build_slate(corpus["user"].id, corpus["topic"].id, rng=RNG)

    assert slate is not None
    difficulties = await _difficulties(session, slate.card_ids)
    assert difficulties.count(Difficulty.BEGINNER) == 10
    assert difficulties.count(Difficulty.INTERMEDIATE) == 0


async def test_slate_respects_the_difficulty_mix_past_the_ramp(
    session: AsyncSession, corpus: dict[str, Any], settings: Settings
) -> None:
    """Once read_fraction reaches `mix_ramp_end`, the mix is the configured
    80/20, exactly — not approximately."""

    await _seed_read_fraction(
        session, corpus["user"].id, corpus["topic"].id, Difficulty.BEGINNER, seen=8, total=12
    )
    service = FeedService(session, Settings(slate_size=10, rank_epsilon=0.0))
    slate = await service.build_slate(corpus["user"].id, corpus["topic"].id, rng=RNG)

    assert slate is not None
    difficulties = await _difficulties(session, slate.card_ids)
    assert difficulties.count(Difficulty.BEGINNER) == 8
    assert difficulties.count(Difficulty.INTERMEDIATE) == 2


async def test_short_pool_serves_short_rather_than_wrong(
    session: AsyncSession, corpus: dict[str, Any]
) -> None:
    """The intermediate pool holds 2 cards; a 25-slot slate wants 5 (once past
    the ramp, so intermediate is actually requested at all).

    We serve 2, never 3 beginner cards wearing an intermediate slot.
    """

    await _seed_read_fraction(
        session, corpus["user"].id, corpus["topic"].id, Difficulty.BEGINNER, seen=8, total=12
    )
    service = FeedService(session, Settings(slate_size=25, rank_epsilon=0.0))
    slate = await service.build_slate(corpus["user"].id, corpus["topic"].id, rng=RNG)

    assert slate is not None
    difficulties = await _difficulties(session, slate.card_ids)
    assert difficulties.count(Difficulty.INTERMEDIATE) == 2
    assert difficulties.count(Difficulty.BEGINNER) == 12


async def test_seen_cards_never_return(
    session: AsyncSession, corpus: dict[str, Any], settings: Settings
) -> None:
    service = FeedService(session, Settings(slate_size=10, rank_epsilon=0.0))
    engagement = EngagementService(session, settings)

    first = await service.build_slate(corpus["user"].id, corpus["topic"].id, rng=RNG)
    assert first is not None
    completed = first.card_ids[0]

    await engagement.ingest(
        corpus["user"].id,
        [
            IncomingEvent(
                id=UUID(int=1),
                card_id=completed,
                kind=EngagementKind.EXPLICIT_COMPLETE,
            )
        ],
    )

    rebuilt = await service.build_slate(corpus["user"].id, corpus["topic"].id, rng=RNG)
    assert rebuilt is not None
    assert completed not in rebuilt.card_ids


async def test_deferred_is_held_back_while_unseen_cards_remain(
    session: AsyncSession, corpus: dict[str, Any], settings: Settings
) -> None:
    """Scrolling past costs the user nothing — but the card does not come straight
    back either, or the feed would loop on whatever they skipped.

    Fresh material always outranks a repeat: while ANY unseen card is left at this
    difficulty, the deferred one waits.
    """

    user_id = corpus["user"].id
    topic_id = corpus["topic"].id
    service = FeedService(session, Settings(slate_size=10, rank_epsilon=0.0))
    engagement = EngagementService(session, settings)

    beginners = [card for card in corpus["cards"] if card.difficulty is Difficulty.BEGINNER]
    skipped = beginners[0].id

    await engagement.ingest(
        user_id,
        [IncomingEvent(id=UUID(int=2), card_id=skipped, kind=EngagementKind.SKIP)],
    )

    state = await session.scalar(
        select(UserCardState).where(
            UserCardState.user_id == user_id, UserCardState.card_id == skipped
        )
    )
    assert state is not None
    assert state.state is SeenState.DEFERRED
    assert state.deferred_cycle == 0

    # Every other beginner card is still UNSEEN, so there is plenty to serve.
    slate = await service.build_slate(user_id, topic_id, rng=RNG)
    assert slate is not None
    assert skipped not in slate.card_ids, "deferred must wait while unseen cards remain"

    cycle = await session.scalar(
        select(UserTopicCycle.cycle).where(
            UserTopicCycle.user_id == user_id,
            UserTopicCycle.topic_id == topic_id,
            UserTopicCycle.difficulty == Difficulty.BEGINNER,
        )
    )
    assert cycle is None, "nothing was exhausted, so nothing should have turned over"


async def test_difficulty_turns_over_once_everything_has_been_shown(
    session: AsyncSession, corpus: dict[str, Any], settings: Settings
) -> None:
    """The second pass, which is the whole point of DEFERRED.

    `UserTopicCycle` promised this in its docstring and nothing implemented it:
    the table was read in two places and written in none, so `cycle` was
    permanently 0 and the eligibility predicate `deferred_cycle < current_cycle`
    was `0 < 0` — the deferred pile could never be released. A reader who reached
    the end of a difficulty simply ran out of feed.

    Now the difficulty turns over on its own, in `build_slate`, the moment
    nothing unseen is left and something is waiting.
    """

    user_id = corpus["user"].id
    topic_id = corpus["topic"].id
    service = FeedService(session, Settings(slate_size=10, rank_epsilon=0.0))
    engagement = EngagementService(session, settings)

    beginners = [card for card in corpus["cards"] if card.difficulty is Difficulty.BEGINNER]
    skipped = beginners[0].id

    await engagement.ingest(
        user_id,
        [IncomingEvent(id=UUID(int=2), card_id=skipped, kind=EngagementKind.SKIP)],
    )
    # Retire every other beginner card, so the deferred one is the only thing that
    # *could* appear. Otherwise this asserts on a ranking tie-break rather than on
    # the cycling behaviour it is meant to cover.
    await engagement.ingest(
        user_id,
        [
            IncomingEvent(
                id=UUID(int=100 + index),
                card_id=card.id,
                kind=EngagementKind.EXPLICIT_COMPLETE,
            )
            for index, card in enumerate(beginners[1:])
        ],
    )

    slate = await service.build_slate(user_id, topic_id, rng=RNG)
    assert slate is not None
    assert skipped in slate.card_ids, "the deferred card must come back once nothing else is left"

    cycle = await session.scalar(
        select(UserTopicCycle.cycle).where(
            UserTopicCycle.user_id == user_id,
            UserTopicCycle.topic_id == topic_id,
            UserTopicCycle.difficulty == Difficulty.BEGINNER,
        )
    )
    assert cycle == 1, "the difficulty should have advanced exactly one cycle"


async def test_an_empty_difficulty_does_not_turn_over(
    session: AsyncSession, corpus: dict[str, Any], settings: Settings
) -> None:
    """Turning over requires something to release.

    A difficulty with nothing deferred is not finished, it is starved — and
    bumping its counter would paper over a pool that ought to be reported and
    generated into instead.
    """

    user_id = corpus["user"].id
    topic_id = corpus["topic"].id
    service = FeedService(session, Settings(slate_size=10, rank_epsilon=0.0))
    engagement = EngagementService(session, settings)

    beginners = [card for card in corpus["cards"] if card.difficulty is Difficulty.BEGINNER]
    # Everything READ, nothing merely shown: the deferred pile is empty.
    await engagement.ingest(
        user_id,
        [
            IncomingEvent(
                id=UUID(int=200 + index),
                card_id=card.id,
                kind=EngagementKind.EXPLICIT_COMPLETE,
            )
            for index, card in enumerate(beginners)
        ],
    )

    await service.build_slate(user_id, topic_id, rng=RNG)

    cycle = await session.scalar(
        select(UserTopicCycle.cycle).where(
            UserTopicCycle.user_id == user_id,
            UserTopicCycle.topic_id == topic_id,
            UserTopicCycle.difficulty == Difficulty.BEGINNER,
        )
    )
    assert cycle is None, "nothing deferred means nothing to release"


async def test_skip_cannot_walk_a_seen_card_backwards(
    session: AsyncSession, corpus: dict[str, Any], settings: Settings
) -> None:
    """SEEN is terminal. A late-arriving skip from a buffered client batch must not
    undo progression the user already earned."""

    user_id = corpus["user"].id
    card_id = corpus["cards"][0].id
    engagement = EngagementService(session, settings)

    await engagement.ingest(
        user_id,
        [IncomingEvent(id=UUID(int=3), card_id=card_id, kind=EngagementKind.EXPLICIT_COMPLETE)],
    )
    await engagement.ingest(
        user_id,
        [IncomingEvent(id=UUID(int=4), card_id=card_id, kind=EngagementKind.SKIP)],
    )

    state = await session.scalar(
        select(UserCardState).where(
            UserCardState.user_id == user_id, UserCardState.card_id == card_id
        )
    )
    assert state is not None
    assert state.state is SeenState.SEEN


async def test_page_returns_ranked_order(session: AsyncSession, corpus: dict[str, Any]) -> None:
    service = FeedService(session, Settings(page_size=5, slate_size=10, rank_epsilon=0.0))
    page = await service.page(corpus["user"].id, rng=RNG)

    assert len(page.card_ids) == 5
    assert len(set(page.card_ids)) == 5, "a page must never repeat a card"


async def test_a_page_never_repeats_a_card_when_a_slate_runs_dry(
    session: AsyncSession, corpus: dict[str, Any]
) -> None:
    """Regression: the same card appeared twice on one page.

    Serving a card does not make it ineligible — it stays UNSEEN until the user
    does something with it. So when a slate ran dry mid-page and was rebuilt, the
    rebuild legitimately re-picked cards that had just been handed out.

    ADR-0010: "a bug here shows as 'I keep seeing the same cards', which is the
    most damaging feed bug there is."
    """

    # A slate far smaller than the page forces at least one mid-page rebuild.
    service = FeedService(session, Settings(page_size=10, slate_size=3, rank_epsilon=0.0))
    page = await service.page(corpus["user"].id, rng=RNG)

    assert len(page.card_ids) == len(set(page.card_ids)), "a page must never repeat a card"


async def test_paging_does_not_repeat_cards(session: AsyncSession, corpus: dict[str, Any]) -> None:
    service = FeedService(session, Settings(page_size=4, slate_size=14, rank_epsilon=0.0))

    first = await service.page(corpus["user"].id, rng=RNG)
    second = await service.page(corpus["user"].id, rng=RNG)

    assert not set(first.card_ids) & set(second.card_ids)


async def test_user_with_no_subscriptions_gets_an_empty_feed(
    session: AsyncSession, corpus: dict[str, Any], settings: Settings
) -> None:
    """An ordinary state, not an error."""

    from spoin.domain.models import User

    stranger = User(email="stranger@test.local", display_name="Stranger")
    session.add(stranger)
    await session.flush()

    page = await FeedService(session, settings).page(stranger.id, rng=RNG)
    assert page.card_ids == []
    assert page.exhausted is True


async def _difficulties(session: AsyncSession, card_ids: list[UUID]) -> list[Difficulty]:
    rows = (
        await session.execute(select(Card.id, Card.difficulty).where(Card.id.in_(card_ids)))
    ).all()
    by_id = {row[0]: row[1] for row in rows}
    return [by_id[card_id] for card_id in card_ids]
