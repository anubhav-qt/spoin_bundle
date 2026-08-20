"""Feed serving.

    per topic:      SELECT (stratified) -> RANK (within strata) -> SLATE (~25)
    across topics:  INTERLEAVE PLAN (affinity-weighted) -> page from the plan

Hard rule 1: **no LLM call may appear anywhere in this module, or anything it
calls.** A swipe is ~50ms; an LLM call is 2-10 seconds. They cannot share a code
path. If you find yourself wanting a model here, the answer is a batch job that
precomputes a column.

The second rule this module obeys: no aggregation at request time. Every score
input is a precomputed column maintained by a batch job (ADR-0011). No COUNT(*)
over engagement, no window functions over event history. That is what keeps the
read path under 100ms with no cache layer, and it is why Redis is not needed yet.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Float, Select, and_, cast, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from spoin.core.config import DIFFICULTY_MIX, Settings
from spoin.domain.enums import CardStatus, Difficulty, SeenState
from spoin.domain.models import (
    Card,
    CardStats,
    FeedPlan,
    FeedSlate,
    Subtopic,
    UserCardState,
    UserSubtopicProgress,
    UserTopic,
    UserTopicAffinity,
    UserTopicCycle,
    UserTopicDifficultyProgress,
    UserTopicProgress,
)
from spoin.feed.interleave import build_plan, filter_key
from spoin.feed.ranking import Candidate, diversify, rank
from spoin.feed.strata import MixOutcome, dynamic_mix, resolve_mix


@dataclass(frozen=True)
class FeedPage:
    card_ids: list[UUID]
    #: Position into the interleave plan. A single integer, which is what keeps
    #: pagination simple despite the ranked set underneath shifting constantly.
    next_position: int
    #: True when a starved pool meant we served a short page. The client must show
    #: an honest "more coming soon" — on free tier a fill can take hours, not
    #: seconds, so an indefinite spinner is a lie.
    degraded: bool
    exhausted: bool
    #: Slots the mix asked for and the corpus could not supply. The caller enqueues
    #: a coalesced fill job for each.
    starved: list[tuple[UUID, Difficulty]]


class FeedService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings

    # ------------------------------------------------------------------ page --
    async def page(
        self,
        user_id: UUID,
        *,
        topic_filter: list[UUID] | None = None,
        position: int | None = None,
        rng: random.Random | None = None,
    ) -> FeedPage:
        settings = self._settings
        plan = await self._ensure_plan(user_id, topic_filter)
        if not plan.topic_order:
            return FeedPage([], 0, degraded=False, exhausted=True, starved=[])

        cursor = plan.position if position is None else position
        card_ids: list[UUID] = []
        degraded = False
        starved: list[tuple[UUID, Difficulty]] = []
        exhausted = False

        # Every card handed out during this call.
        #
        # Serving a card does not make it ineligible — it stays UNSEEN until the
        # user does something with it. So when a slate runs dry mid-page and is
        # rebuilt, the rebuild legitimately re-picks cards we just served, and the
        # same card appears twice on one page. Tracking what went out and skipping
        # it is what stops that, and it is also passed into any rebuild so the new
        # slate is built without them in the first place.
        served: set[UUID] = set()

        # Walk the plan, drawing one card from each topic's slate in turn. A topic
        # whose slate is empty is skipped rather than ending the page — one starved
        # topic must not starve the others.
        attempts = 0
        max_attempts = len(plan.topic_order) * 2
        while len(card_ids) < settings.page_size and attempts < max_attempts:
            if cursor >= len(plan.topic_order):
                cursor = 0
            topic_id = plan.topic_order[cursor]
            cursor += 1
            attempts += 1

            slate = await self._ensure_slate(user_id, topic_id, rng=rng, exclude=served)
            if slate is None:
                continue
            degraded = degraded or slate.degraded

            # Skip past anything already served this page rather than emitting it
            # again.
            while slate.position < len(slate.card_ids) and slate.card_ids[slate.position] in served:
                slate.position += 1

            if slate.position >= len(slate.card_ids):
                continue

            card_id = slate.card_ids[slate.position]
            card_ids.append(card_id)
            served.add(card_id)
            slate.position += 1
            attempts = 0

        if len(card_ids) < settings.page_size:
            exhausted = True
            starved = await self._starved_slots(user_id, plan.topic_order)

        plan.position = cursor
        await self._session.flush()

        return FeedPage(
            card_ids=card_ids,
            next_position=cursor,
            degraded=degraded,
            exhausted=exhausted,
            starved=starved,
        )

    # ------------------------------------------------------------------ plan --
    async def _ensure_plan(self, user_id: UUID, topic_filter: list[UUID] | None) -> FeedPlan:
        key = filter_key(topic_filter)
        existing = await self._session.scalar(select(FeedPlan).where(FeedPlan.user_id == user_id))

        if existing is not None and existing.filter_key == key:
            return existing

        affinities = await self._affinities(user_id, topic_filter)
        order = build_plan(
            affinities,
            self._settings.plan_size,
            # A single-topic filter has nothing to alternate with, so runs are
            # irrelevant there; the client switches to subtopic headings anyway.
            run_length=self._settings.feed_topic_run,
        )

        if existing is None:
            # Upsert, not a plain INSERT: two concurrent requests for a user with
            # no plan yet (e.g. a double-fired feed fetch) can both reach this
            # branch having seen `existing is None`, and both attempt to insert,
            # racing `uq_feed_plan_user_id`. ON CONFLICT makes the second writer
            # update in place instead of crashing with a 500.
            statement = (
                pg_insert(FeedPlan)
                .values(user_id=user_id, topic_order=order, position=0, filter_key=key)
                .on_conflict_do_update(
                    index_elements=["user_id"],
                    set_={"topic_order": order, "position": 0, "filter_key": key},
                )
            )
            await self._session.execute(statement)
            existing = await self._session.scalar(
                select(FeedPlan).where(FeedPlan.user_id == user_id)
            )
        else:
            # A filter change regenerates the plan only. Slates are retained, not
            # discarded, so unfiltering resumes every topic exactly where it was.
            existing.topic_order = order
            existing.position = 0
            existing.filter_key = key

        await self._session.flush()
        return existing

    async def _affinities(
        self, user_id: UUID, topic_filter: list[UUID] | None
    ) -> dict[UUID, float]:
        stmt = (
            select(UserTopic.topic_id, func.coalesce(UserTopicAffinity.affinity, 1.0))
            .select_from(UserTopic)
            .outerjoin(
                UserTopicAffinity,
                and_(
                    UserTopicAffinity.user_id == UserTopic.user_id,
                    UserTopicAffinity.topic_id == UserTopic.topic_id,
                ),
            )
            .where(UserTopic.user_id == user_id)
        )
        if topic_filter:
            stmt = stmt.where(UserTopic.topic_id.in_(topic_filter))

        rows = (await self._session.execute(stmt)).all()
        return {row[0]: float(row[1]) for row in rows}

    # ----------------------------------------------------------------- slate --
    async def _ensure_slate(
        self,
        user_id: UUID,
        topic_id: UUID,
        *,
        rng: random.Random | None,
        exclude: set[UUID] | None = None,
    ) -> FeedSlate | None:
        now = datetime.now(UTC)
        slate = await self._session.scalar(
            select(FeedSlate).where(FeedSlate.user_id == user_id, FeedSlate.topic_id == topic_id)
        )

        fresh_enough = (
            slate is not None and slate.expires_at > now and slate.position < len(slate.card_ids)
        )
        if slate is not None and fresh_enough:
            return slate

        return await self.build_slate(user_id, topic_id, rng=rng, exclude=exclude)

    async def build_slate(
        self,
        user_id: UUID,
        topic_id: UUID,
        *,
        rng: random.Random | None = None,
        exclude: set[UUID] | None = None,
    ) -> FeedSlate | None:
        """Rank one topic's eligible cards into a ~25-card slate.

        Expensive, and deliberately so — it is the layer where invalidation is
        rare. Slates refill independently rather than all-or-nothing, and topics
        the user is not currently reading cost nothing to re-rank.
        """

        settings = self._settings
        now = datetime.now(UTC)
        tier = await self._current_tier(user_id, topic_id)

        previous = await self._session.scalar(
            select(FeedSlate).where(FeedSlate.user_id == user_id, FeedSlate.topic_id == topic_id)
        )
        was_degraded = previous.degraded if previous is not None else False

        # One query per stratum — this is what makes the mix exact rather than
        # emergent. Ranking happens WITHIN each stratum, never across them.
        blocked = exclude or set()
        candidates_by_tier: dict[Difficulty, list[Candidate]] = {}
        for difficulty in Difficulty:
            found = await self._candidates(user_id, topic_id, difficulty)
            candidates_by_tier[difficulty] = [c for c in found if c.card_id not in blocked]

        read_fraction = await self._tier_read_fraction(user_id, topic_id, tier)
        mix_override = dynamic_mix(
            tier,
            read_fraction,
            ramp_start=settings.mix_ramp_start,
            ramp_end=settings.mix_ramp_end,
        )

        outcome: MixOutcome = resolve_mix(
            settings.slate_size,
            tier,
            {d: len(c) for d, c in candidates_by_tier.items()},
            was_degraded=was_degraded,
            pool_low=settings.pool_low,
            pool_high=settings.pool_high,
            mix_override=mix_override,
        )

        picked: list[Candidate] = []
        for fill in outcome.fills:
            picked += rank(
                candidates_by_tier[fill.difficulty],
                settings,
                now=now,
                limit=fill.served,
                rng=rng,
            )

        if not picked:
            return None

        card_ids = [candidate.card_id for candidate in diversify(picked)]
        expires_at = now + timedelta(seconds=settings.slate_ttl_seconds)

        if previous is None:
            previous = FeedSlate(
                user_id=user_id,
                topic_id=topic_id,
                card_ids=card_ids,
                position=0,
                degraded=outcome.degraded,
                expires_at=expires_at,
            )
            self._session.add(previous)
        else:
            previous.card_ids = card_ids
            previous.position = 0
            previous.degraded = outcome.degraded
            previous.expires_at = expires_at

        await self._session.flush()
        return previous

    # ------------------------------------------------------------ candidates --
    # The last column (`coverage_need`) comes back as Decimal, not float: Postgres
    # promotes the division to numeric. `_candidates` converts it. Annotated
    # honestly rather than cast in SQL, since a cast would only hide what the
    # driver actually hands back.
    def _eligible_cards(
        self, user_id: UUID, topic_id: UUID, difficulty: Difficulty
    ) -> Select[tuple[UUID, UUID, datetime, float, float | Decimal]]:
        """Eligible = UNSEEN, or DEFERRED in an earlier cycle.

        SEEN never returns — it counts toward the 80% gate. DEFERRED comes back
        once the cycle advances, which is what makes scrolling past cost the user
        nothing.
        """

        current_cycle = (
            select(func.coalesce(UserTopicCycle.cycle, 0))
            .where(
                UserTopicCycle.user_id == user_id,
                UserTopicCycle.topic_id == topic_id,
                UserTopicCycle.difficulty == difficulty,
            )
            .scalar_subquery()
        )

        return (
            select(
                Card.id,
                Card.subtopic_id,
                Card.created_at,
                func.coalesce(CardStats.quality, 0.0),
                # coverage_need = 1 - seen/total. NULLIF guards a subtopic with no
                # cards yet, and COALESCE makes an untouched subtopic maximally
                # needy rather than NULL — which is the behaviour we want, since a
                # subtopic the user has never opened is exactly what should surface.
                func.coalesce(
                    1.0
                    - cast(UserSubtopicProgress.seen_count, Float)
                    / func.nullif(UserSubtopicProgress.total_count, 0),
                    1.0,
                ),
            )
            .select_from(Card)
            .join(Subtopic, Subtopic.id == Card.subtopic_id)
            .outerjoin(CardStats, CardStats.card_id == Card.id)
            .outerjoin(
                UserCardState,
                and_(UserCardState.card_id == Card.id, UserCardState.user_id == user_id),
            )
            .outerjoin(
                UserSubtopicProgress,
                and_(
                    UserSubtopicProgress.subtopic_id == Card.subtopic_id,
                    UserSubtopicProgress.user_id == user_id,
                ),
            )
            .where(
                Card.topic_id == topic_id,
                Card.difficulty == difficulty,
                Card.status == CardStatus.ACTIVE,
                or_(
                    UserCardState.state.is_(None),
                    UserCardState.state == SeenState.UNSEEN,
                    and_(
                        UserCardState.state == SeenState.DEFERRED,
                        UserCardState.deferred_cycle < current_cycle,
                    ),
                ),
            )
            # A generous multiple of the slate, so ranking has something to choose
            # between without pulling the whole corpus into memory.
            .limit(self._settings.slate_size * 4)
        )

    async def _candidates(
        self, user_id: UUID, topic_id: UUID, difficulty: Difficulty
    ) -> list[Candidate]:
        affinity = await self._session.scalar(
            select(UserTopicAffinity.affinity).where(
                UserTopicAffinity.user_id == user_id,
                UserTopicAffinity.topic_id == topic_id,
            )
        )
        rows = (
            await self._session.execute(self._eligible_cards(user_id, topic_id, difficulty))
        ).all()

        return [
            Candidate(
                card_id=row[0],
                subtopic_id=row[1],
                created_at=row[2],
                card_quality=float(row[3]),
                topic_affinity=float(affinity if affinity is not None else 1.0),
                coverage_need=float(row[4]),
            )
            for row in rows
        ]

    # ---------------------------------------------------------------- helpers --
    async def _current_tier(self, user_id: UUID, topic_id: UUID) -> Difficulty:
        tier = await self._session.scalar(
            select(UserTopicProgress.current_difficulty).where(
                UserTopicProgress.user_id == user_id,
                UserTopicProgress.topic_id == topic_id,
            )
        )
        return tier or Difficulty.BEGINNER

    async def _tier_read_fraction(self, user_id: UUID, topic_id: UUID, tier: Difficulty) -> float:
        """How much of THIS topic's `tier` cards this user has already read —
        `dynamic_mix`'s input. A single row read against the precomputed
        `UserTopicDifficultyProgress` aggregate (kept current by
        `engagement/service.py`'s `_bump_difficulty_progress`), not a COUNT at
        request time (ADR-0011). No row yet (nothing read at this tier) or a
        tier with no cards at all both read as 0 -- the ramp's own start,
        which is exactly right for "hasn't started this difficulty."
        """

        row = await self._session.execute(
            select(
                UserTopicDifficultyProgress.seen_count, UserTopicDifficultyProgress.total_count
            ).where(
                UserTopicDifficultyProgress.user_id == user_id,
                UserTopicDifficultyProgress.topic_id == topic_id,
                UserTopicDifficultyProgress.difficulty == tier,
            )
        )
        found = row.first()
        if found is None or not found[1]:
            return 0.0
        return float(found[0]) / float(found[1])

    async def _starved_slots(
        self, user_id: UUID, topic_ids: list[UUID]
    ) -> list[tuple[UUID, Difficulty]]:
        """Which (topic, difficulty) slots came up short.

        The caller turns these into fill jobs. ADR-0007 amended the coalescing key
        to `subtopic_id`; the worker resolves a starved tier down to the specific
        subtopics sitting below `min_cards`, which is a far sharper signal than
        "this topic's pool is low".
        """

        starved: list[tuple[UUID, Difficulty]] = []
        for topic_id in topic_ids:
            tier = await self._current_tier(user_id, topic_id)
            # Only the strata this user's mix actually asks for. A beginner has no
            # advanced slice, so an empty advanced pool is not starvation for them.
            for difficulty in DIFFICULTY_MIX[tier]:
                if not await self._has_eligible(user_id, topic_id, difficulty):
                    starved.append((topic_id, difficulty))
        return starved

    async def _has_eligible(self, user_id: UUID, topic_id: UUID, difficulty: Difficulty) -> bool:
        stmt = self._eligible_cards(user_id, topic_id, difficulty).limit(1)
        return (await self._session.execute(stmt)).first() is not None

    async def invalidate(self, user_id: UUID) -> None:
        """Drop this user's plan. Called on subscription change.

        Slates survive deliberately — see `_ensure_plan`.
        """

        await self._session.execute(delete(FeedPlan).where(FeedPlan.user_id == user_id))
