"""Topic subscriptions, discovery, and tier progression.

Moved wholesale out of `api/routers/topics.py`, which held 48 SQL statements
across 13 handlers — the largest concentration of database access in the
codebase outside the generation pipeline, and the one place where an LLM call,
the custom-topic quota, the subscription writes and the progression latch all
lived inside a single HTTP handler (`request_topic`, 107 lines).

The progression helpers are the reason this matters most. `ensure_unlock_latched`
was defined in a router and imported *by another router* (`quiz.py`), which is
the shape a service layer exists to prevent: two transport modules coupled to
each other so they can share a domain rule. Both call this now.

**Why the read methods return `*Out` schemas.** They are the app's DTOs, plain
Pydantic with no FastAPI coupling, and `ProfileService` already returns them
(`ProfileStatsOut`, `ProfileExportOut`). Defining a parallel dataclass for each
of eight response shapes would double the type count without changing a line of
behaviour. Write paths that carry real domain decisions return their result
plus enough context for the router to serialize.

Serving layer, with one documented exception: `request_topic` calls the
generator to sanity-check a user-supplied topic name (ADR-0025). That is a
user-initiated write, never the feed read path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from spoin.api.schemas import (
    CustomTopicStatusOut,
    GenerationProgressOut,
    GenerationSubtopicProgressOut,
    OnboardingTopicChoice,
    ProgressOut,
    SubtopicProgressOut,
    TopicCurriculumOut,
    TopicDiscoverOut,
    TopicOut,
    TopicStatsOut,
)
from spoin.core.config import Settings
from spoin.domain.enums import CardStatus, Difficulty, EngagementKind, SeenState
from spoin.domain.models import (
    Card,
    CardBookmark,
    CardLike,
    EngagementEvent,
    GenerationJob,
    Subtopic,
    Topic,
    User,
    UserCardState,
    UserTopic,
    UserTopicProgress,
)
from spoin.embeddings import Embedder
from spoin.generation.base import ContentGenerator, TopicNameQuery
from spoin.generation.pipeline import TopicRequest, match_and_create_topics

#: Notes/shares have no mutable-state table (ADR-0015) — these are the only two
#: kinds `/topics/{id}/stats` aggregates from the raw event log rather than a
#: current-state count.
_STATS_EVENT_KINDS = (EngagementKind.NOTE, EngagementKind.SHARE)

#: How many rows `discover` returns.
_DISCOVER_LIMIT = 5


def entry_tier_unlock(entry: Difficulty) -> list[bool]:
    """ADR-0032 (amends ADR-0027): only tiers STRICTLY BELOW the chosen entry
    tier start unlocked. The entry tier itself still earns its quiz through the
    normal coverage gate."""

    return [tier.rank < entry.rank for tier in Difficulty]


@dataclass(frozen=True)
class RequestedTopic:
    topic: TopicOut
    #: "generating" when a brand-new topic was minted and a job enqueued;
    #: "subscribed" when the name canonicalized onto a topic that already exists.
    status: Literal["generating", "subscribed"]


class TopicsService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings

    # -- reads ---------------------------------------------------------------

    async def list_subscribed(self, user_id: UUID) -> list[TopicOut]:
        rows = (
            await self._session.execute(
                select(UserTopic, Topic, UserTopicProgress.current_difficulty)
                .join(Topic, Topic.id == UserTopic.topic_id)
                .outerjoin(
                    UserTopicProgress,
                    (UserTopicProgress.user_id == UserTopic.user_id)
                    & (UserTopicProgress.topic_id == UserTopic.topic_id),
                )
                .where(UserTopic.user_id == user_id)
                .order_by(UserTopic.created_at)
            )
        ).all()

        return [
            TopicOut(
                id=topic.id,
                # The user's own label, never the canonical name.
                display_name=user_topic.display_name,
                slug=topic.slug,
                is_custom=user_topic.is_custom,
                current_difficulty=tier or Difficulty.BEGINNER,
                accent_hue=user_topic.accent_hue,
            )
            for user_topic, topic, tier in rows
        ]

    async def list_custom(self, user_id: UUID) -> list[CustomTopicStatusOut]:
        """This user's custom (self-requested) topics, each with its most recent
        `GenerationJob` status -- a user otherwise has no way to tell "still
        generating" from "broken" from "nothing was ever queued".

        A topic can in principle have more than one `GenerationJob` row over its
        lifetime (retried failures, say) even though at most one is ever
        pending/running at once (the model's coalescing index) -- so this reads
        the latest by `created_at`, not an unqualified join.

        The status lookup was a query per topic in a loop. Bounded by
        `custom_topic_limit` (3), so never pathological, but it is one grouped
        query now rather than N+1 — the row count is a product decision that
        could change, and the query shouldn't have to change with it.
        """

        rows = (
            await self._session.execute(
                select(UserTopic, Topic)
                .join(Topic, Topic.id == UserTopic.topic_id)
                .where(UserTopic.user_id == user_id, UserTopic.is_custom.is_(True))
                .order_by(UserTopic.created_at)
            )
        ).all()
        if not rows:
            return []

        topic_ids = [topic.id for _, topic in rows]
        latest = await self._latest_jobs_by_topic(topic_ids)

        return [
            CustomTopicStatusOut(
                topic_id=topic.id,
                display_name=user_topic.display_name,
                slug=topic.slug,
                generation_status=latest[topic.id].status if topic.id in latest else None,
                requested_at=user_topic.created_at,
            )
            for user_topic, topic in rows
        ]

    async def _latest_jobs_by_topic(self, topic_ids: list[UUID]) -> dict[UUID, GenerationJob]:
        """Most recent job per topic, in one round trip.

        `DISTINCT ON` rather than a window function: Postgres-only, but this
        codebase is Postgres-only by design (pgvector), and it reads as exactly
        what it does.
        """

        if not topic_ids:
            return {}
        rows = (
            (
                await self._session.execute(
                    select(GenerationJob)
                    .where(GenerationJob.topic_id.in_(topic_ids))
                    .distinct(GenerationJob.topic_id)
                    .order_by(GenerationJob.topic_id, GenerationJob.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        return {job.topic_id: job for job in rows}

    async def generation_progress(self, topic_id: UUID) -> GenerationProgressOut:
        """Polled by the request-a-topic streaming UI while a custom topic's
        `GenerationJob` is in flight.

        No ownership check beyond authentication -- `GenerationJob`/`Topic`
        carry nothing user-specific, so this is no more sensitive than the
        corpus data every other topic-reading endpoint already returns to any
        signed-in user.
        """

        job = await self._session.scalar(
            select(GenerationJob)
            .where(GenerationJob.topic_id == topic_id)
            .order_by(GenerationJob.created_at.desc())
            .limit(1)
        )
        if job is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, detail="No generation job for this topic"
            )

        progress = job.progress or {}
        stage = None if job.status == "pending" else progress.get("stage", "curriculum")
        raw_subtopics = cast("list[dict[str, object]]", progress.get("subtopics", []))

        return GenerationProgressOut(
            status=cast(Literal["pending", "running", "completed", "failed"], job.status),
            stage=cast("Literal['curriculum', 'cards', 'done'] | None", stage),
            topic_name=cast("str | None", progress.get("topic_name")),
            subtopics=[GenerationSubtopicProgressOut(**entry) for entry in raw_subtopics],
            error=job.last_error if job.status == "failed" else None,
        )

    async def list_all(self, user_id: UUID) -> list[TopicDiscoverOut]:
        """Every topic in the corpus, not just the top-5 unfollowed slice
        `discover` returns (ADR-0038).

        `followed` lets the client grey out Follow on a row instead of offering
        a second subscribe -- cheaper than filtering those rows out entirely,
        since "browse everything" should still show what you're already
        following.
        """

        followed_ids = set(
            (
                await self._session.execute(
                    select(UserTopic.topic_id).where(UserTopic.user_id == user_id)
                )
            )
            .scalars()
            .all()
        )

        rows = (
            (await self._session.execute(select(Topic).order_by(Topic.subscriber_count.desc())))
            .scalars()
            .all()
        )

        return [
            TopicDiscoverOut(
                topic_id=topic.id,
                display_name=topic.canonical_name,
                subscriber_count=topic.subscriber_count,
                followed=topic.id in followed_ids,
            )
            for topic in rows
        ]

    async def discover(self, user_id: UUID) -> list[TopicDiscoverOut]:
        """Top N topics the user doesn't already follow, ranked by
        subscriber_count.

        The route's `mode` parameter is not threaded through: `for_you` runs the
        identical query today (ADR-0015, task 0003 — there is no signal yet to
        personalize from for topics a user hasn't subscribed to), and a
        parameter this method ignores would be a lie about what it does. The
        route keeps accepting it so the client toggle doesn't change shape.
        """

        followed = select(UserTopic.topic_id).where(UserTopic.user_id == user_id)
        rows = (
            (
                await self._session.execute(
                    select(Topic)
                    .where(Topic.id.not_in(followed))
                    .order_by(Topic.subscriber_count.desc())
                    .limit(_DISCOVER_LIMIT)
                )
            )
            .scalars()
            .all()
        )

        return [
            TopicDiscoverOut(
                topic_id=topic.id,
                display_name=topic.canonical_name,
                subscriber_count=topic.subscriber_count,
            )
            for topic in rows
        ]

    async def stats(self, user_id: UUID, topic_id: UUID) -> TopicStatsOut:
        tier, coverage, unlocked, mastered = await self.progress_snapshot(user_id, topic_id)

        progress = await self._session.scalar(
            select(UserTopicProgress).where(
                UserTopicProgress.user_id == user_id,
                UserTopicProgress.topic_id == topic_id,
            )
        )
        likes = await self._session.scalar(
            select(func.count())
            .select_from(CardLike)
            .join(Card, Card.id == CardLike.card_id)
            .where(CardLike.user_id == user_id, Card.topic_id == topic_id)
        )
        saves = await self._session.scalar(
            select(func.count())
            .select_from(CardBookmark)
            .join(Card, Card.id == CardBookmark.card_id)
            .where(CardBookmark.user_id == user_id, Card.topic_id == topic_id)
        )

        event_rows = (
            await self._session.execute(
                select(EngagementEvent.kind, func.count())
                .where(
                    EngagementEvent.user_id == user_id,
                    EngagementEvent.topic_id == topic_id,
                    EngagementEvent.kind.in_(_STATS_EVENT_KINDS),
                )
                .group_by(EngagementEvent.kind)
            )
        ).all()
        event_counts: dict[EngagementKind, int] = dict(tuple(row) for row in event_rows)

        return TopicStatsOut(
            topic_id=topic_id,
            current_difficulty=tier,
            coverage=coverage,
            quiz_unlocked=unlocked,
            mastered=mastered,
            tier_quiz_passed=list(progress.tier_quiz_passed) if progress else [False] * 3,
            likes=likes or 0,
            saves=saves or 0,
            notes=event_counts.get(EngagementKind.NOTE, 0),
            shares=event_counts.get(EngagementKind.SHARE, 0),
        )

    async def curriculum(self, user_id: UUID, topic_id: UUID) -> TopicCurriculumOut:
        """Every subtopic across all three tiers, with this user's per-subtopic
        coverage — the detail the aggregate stats are rolled up from. Ordered by
        difficulty then `position`, matching curriculum-authoring order
        (content-model.md), not insertion order.
        """

        rows = (
            await self._session.execute(
                select(
                    Subtopic.id,
                    Subtopic.title,
                    Subtopic.difficulty,
                    func.count(Card.id).filter(Card.status == CardStatus.ACTIVE),
                    func.count(UserCardState.card_id).filter(UserCardState.state == SeenState.SEEN),
                )
                .select_from(Subtopic)
                .outerjoin(Card, Card.subtopic_id == Subtopic.id)
                .outerjoin(
                    UserCardState,
                    (UserCardState.card_id == Card.id) & (UserCardState.user_id == user_id),
                )
                .where(Subtopic.topic_id == topic_id)
                .group_by(Subtopic.id, Subtopic.title, Subtopic.difficulty, Subtopic.position)
                .order_by(Subtopic.difficulty, Subtopic.position)
            )
        ).all()

        gate = self._settings.coverage_gate
        subtopics = [
            SubtopicProgressOut(
                subtopic_id=subtopic_id,
                title=title,
                difficulty=difficulty,
                total_cards=total,
                seen_cards=seen,
                coverage=(seen / total) if total else 0.0,
                # Same gate `_tier_coverage` uses for tier unlock, applied here
                # per subtopic instead of only at the thinnest one.
                covered=(total > 0 and seen / total >= gate),
            )
            for subtopic_id, title, difficulty, total, seen in rows
        ]

        return TopicCurriculumOut(topic_id=topic_id, subtopics=subtopics)

    async def progress(self, user_id: UUID, topic_id: UUID) -> ProgressOut:
        progress, tier, coverage, unlocked, mastered = await self.ensure_unlock_latched(
            user_id, topic_id
        )
        return ProgressOut(
            topic_id=topic_id,
            current_difficulty=tier,
            coverage=coverage,
            quiz_unlocked=unlocked,
            tier_quiz_passed=list(progress.tier_quiz_passed) if progress else [False] * 3,
            mastered=mastered,
        )

    # -- progression ---------------------------------------------------------

    async def ensure_unlock_latched(
        self, user_id: UUID, topic_id: UUID
    ) -> tuple[UserTopicProgress | None, Difficulty, float, bool, bool]:
        """Read the coverage snapshot, then write the tier_unlocked latch if
        newly earned. Shared by the progress endpoint and the start-quiz check,
        so both agree on what's unlocked without duplicating the write.

        The latch itself: once unlocked, it stays unlocked. Recomputing would
        let background generation revoke earned progress, dropping a user from
        8/10 (80%, unlocked) to 8/20 (40%, locked) the moment ten more cards
        land.
        """

        tier, coverage, unlocked, mastered = await self.progress_snapshot(user_id, topic_id)
        progress = await self._session.scalar(
            select(UserTopicProgress).where(
                UserTopicProgress.user_id == user_id,
                UserTopicProgress.topic_id == topic_id,
            )
        )
        already_unlocked = bool(progress and progress.tier_unlocked[tier.rank])
        if unlocked and progress is not None and not already_unlocked:
            latched = list(progress.tier_unlocked)
            latched[tier.rank] = True
            progress.tier_unlocked = latched
            await self._session.commit()
        return progress, tier, coverage, unlocked, mastered

    async def progress_snapshot(
        self, user_id: UUID, topic_id: UUID
    ) -> tuple[Difficulty, float, bool, bool]:
        """Read-only: tier, coverage, unlocked, mastered. No latch write, so a
        read-only caller can reuse it without the side effect."""

        progress = await self._session.scalar(
            select(UserTopicProgress).where(
                UserTopicProgress.user_id == user_id,
                UserTopicProgress.topic_id == topic_id,
            )
        )
        tier = progress.current_difficulty if progress else Difficulty.BEGINNER
        coverage = await self._tier_coverage(user_id, topic_id, tier)
        already_unlocked = bool(progress and progress.tier_unlocked[tier.rank])
        unlocked = already_unlocked or coverage >= self._settings.coverage_gate
        mastered = bool(progress and progress.mastered_at is not None)
        return tier, coverage, unlocked, mastered

    async def _tier_coverage(self, user_id: UUID, topic_id: UUID, tier: Difficulty) -> float:
        """Coverage of the **weakest** subtopic in the tier.

        The gate is "80% of the cards in EVERY subtopic", so the thinnest one
        governs. Averaging across subtopics would let a user coast on one
        well-read subtopic while never opening another.
        """

        rows = (
            await self._session.execute(
                select(
                    Subtopic.id,
                    func.count(Card.id),
                    func.count(UserCardState.card_id).filter(UserCardState.state == SeenState.SEEN),
                )
                .select_from(Subtopic)
                .outerjoin(Card, (Card.subtopic_id == Subtopic.id))
                .outerjoin(
                    UserCardState,
                    (UserCardState.card_id == Card.id) & (UserCardState.user_id == user_id),
                )
                .where(
                    Subtopic.topic_id == topic_id,
                    Subtopic.difficulty == tier,
                    (Card.id.is_(None)) | (Card.status == CardStatus.ACTIVE),
                )
                .group_by(Subtopic.id)
            )
        ).all()

        ratios = [seen / total for _, total, seen in rows if total]
        return min(ratios) if ratios else 0.0

    # -- writes --------------------------------------------------------------

    async def set_color(self, user_id: UUID, topic_id: UUID, hue: int | None) -> TopicOut:
        """ADR-0034: per-subscription accent hue, not a shared `Topic` property
        -- two users may color the same topic differently. `hue=None` resets to
        the deterministic default the client computes itself."""

        user_topic = await self._session.scalar(
            select(UserTopic).where(UserTopic.user_id == user_id, UserTopic.topic_id == topic_id)
        )
        if user_topic is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not subscribed to this topic")

        user_topic.accent_hue = hue
        progress = await self._session.scalar(
            select(UserTopicProgress).where(
                UserTopicProgress.user_id == user_id,
                UserTopicProgress.topic_id == topic_id,
            )
        )
        topic = await self._session.get(Topic, topic_id)
        assert topic is not None
        await self._session.commit()

        return TopicOut(
            id=topic.id,
            display_name=user_topic.display_name,
            slug=topic.slug,
            is_custom=user_topic.is_custom,
            current_difficulty=progress.current_difficulty if progress else Difficulty.BEGINNER,
            accent_hue=user_topic.accent_hue,
        )

    async def subscribe(
        self, user_id: UUID, topic_id: UUID, entry_difficulty: Difficulty
    ) -> TopicOut:
        topic = await self._session.get(Topic, topic_id)
        if topic is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Unknown topic")

        existing = await self._session.scalar(
            select(UserTopic).where(UserTopic.user_id == user_id, UserTopic.topic_id == topic_id)
        )
        if existing is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Already subscribed")

        # No rename UI exists yet (ADR-0004's personal-label split), so the label
        # starts as the canonical name — same default seed.py uses.
        user_topic = UserTopic(
            user_id=user_id,
            topic_id=topic_id,
            display_name=topic.canonical_name,
            is_custom=False,
        )
        self._session.add(user_topic)
        topic.subscriber_count += 1
        self._session.add(
            UserTopicProgress(
                user_id=user_id,
                topic_id=topic_id,
                current_difficulty=entry_difficulty,
                tier_unlocked=entry_tier_unlock(entry_difficulty),
            )
        )
        await self._session.commit()

        return TopicOut(
            id=topic.id,
            display_name=user_topic.display_name,
            slug=topic.slug,
            is_custom=False,
            current_difficulty=entry_difficulty,
        )

    async def complete_onboarding(
        self, user_id: UUID, choices: list[OnboardingTopicChoice]
    ) -> list[TopicOut]:
        """First-run setup: subscribe to the chosen topics, each at its own
        entry tier, then flip the gate the root route checks. Unknown IDs are
        skipped rather than failing the whole request -- onboarding should not
        strand a user over one stale entry in the picker's list."""

        subscribed: list[TopicOut] = []
        for choice in choices:
            topic = await self._session.get(Topic, choice.topic_id)
            if topic is None:
                continue

            existing = await self._session.scalar(
                select(UserTopic).where(
                    UserTopic.user_id == user_id, UserTopic.topic_id == topic.id
                )
            )
            if existing is not None:
                continue

            user_topic = UserTopic(
                user_id=user_id,
                topic_id=topic.id,
                display_name=topic.canonical_name,
                is_custom=False,
            )
            self._session.add(user_topic)
            topic.subscriber_count += 1
            self._session.add(
                UserTopicProgress(
                    user_id=user_id,
                    topic_id=topic.id,
                    current_difficulty=choice.entry_difficulty,
                    tier_unlocked=entry_tier_unlock(choice.entry_difficulty),
                )
            )
            subscribed.append(
                TopicOut(
                    id=topic.id,
                    display_name=user_topic.display_name,
                    slug=topic.slug,
                    is_custom=False,
                    current_difficulty=choice.entry_difficulty,
                )
            )

        user = await self._session.get(User, user_id)
        assert user is not None
        user.onboarding_complete = True

        await self._session.commit()
        return subscribed

    async def request_topic(
        self,
        user_id: UUID,
        *,
        name: str,
        description: str,
        entry_difficulty: Difficulty,
        generator: ContentGenerator,
        embedder: Embedder,
    ) -> RequestedTopic:
        """A user typing a topic name, as opposed to picking one from Discover.

        Runs the name through ADR-0025's batched matcher: a match onto an
        existing topic just subscribes the user (no generation triggered here).
        A genuine miss mints a new `Topic` row and enqueues a `GenerationJob` --
        generation is never synchronous (ADR-0003), so the result reports which
        case happened rather than returning cards.

        Custom topics are gated to non-guest users -- a guest's account is
        ephemeral, so letting it spend one of the custom-topic slots (and
        trigger a real generation job) has no durable payoff and is easy to
        abuse anonymously.

        `generator` and `embedder` are parameters rather than module-level
        singleton lookups so a test can drive this with `FakeContentGenerator`
        and `HashEmbedder` without patching anything global.
        """

        settings = self._settings
        session = self._session

        user = await session.get(User, user_id)
        assert user is not None
        if user.is_guest:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, detail="Sign up to request a custom topic"
            )

        name = name.strip()
        if not name:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Topic name is required"
            )
        if len(name.split()) > settings.custom_topic_max_words:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Keep it short -- {settings.custom_topic_max_words} words or fewer",
            )

        verdicts = await generator.validate_topic_names(
            [TopicNameQuery(request_index=0, name=name)]
        )
        verdict = next((v for v in verdicts.items if v.request_index == 0), None)
        if verdict is not None and not verdict.acceptable:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=verdict.reason or "That doesn't look like a learnable topic",
            )

        custom_count = await session.scalar(
            select(func.count())
            .select_from(UserTopic)
            .where(UserTopic.user_id == user_id, UserTopic.is_custom.is_(True))
        )
        if (custom_count or 0) >= settings.custom_topic_limit:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail=f"Custom topic limit reached ({settings.custom_topic_limit})",
            )

        outcomes = await match_and_create_topics(
            session,
            generator,
            embedder,
            settings,
            topic_requests=[TopicRequest(name=name, description=description.strip())],
        )
        outcome = outcomes[0]
        topic_id = UUID(outcome["topic_id"])

        existing = await session.scalar(
            select(UserTopic).where(UserTopic.user_id == user_id, UserTopic.topic_id == topic_id)
        )
        if existing is not None:
            # Already following the topic this name resolved to -- no slot
            # spent, no second job. Whatever match_and_create_topics did above
            # (at most a new alias row) is still worth keeping, so commit
            # rather than rolling back.
            await session.commit()
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Already subscribed")

        topic = await session.get(Topic, topic_id)
        assert topic is not None

        # The user's own label, same as `subscribe` -- but here it's what they
        # actually typed, not the canonical name they picked from a list.
        user_topic = UserTopic(
            user_id=user_id, topic_id=topic_id, display_name=name, is_custom=True
        )
        session.add(user_topic)
        topic.subscriber_count += 1
        session.add(
            UserTopicProgress(
                user_id=user_id,
                topic_id=topic_id,
                current_difficulty=entry_difficulty,
                tier_unlocked=entry_tier_unlock(entry_difficulty),
            )
        )

        is_new_topic = not outcome["matched_existing"]
        if is_new_topic:
            session.add(GenerationJob(topic_id=topic_id, status="pending"))

        await session.commit()

        return RequestedTopic(
            topic=TopicOut(
                id=topic.id,
                display_name=user_topic.display_name,
                slug=topic.slug,
                is_custom=True,
                current_difficulty=entry_difficulty,
            ),
            status="generating" if is_new_topic else "subscribed",
        )
