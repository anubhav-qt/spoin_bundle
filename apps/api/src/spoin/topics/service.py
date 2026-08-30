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

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, cast
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
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
    TopicRequestIn,
    TopicStatsOut,
)
from spoin.core.config import Settings
from spoin.domain.enums import CardStatus, Difficulty, EngagementKind, SeenState
from spoin.domain.models import (
    Card,
    CardBookmark,
    CardLike,
    EngagementEvent,
    FeedPlan,
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
from spoin.topics.accent_color import (
    NO_TOPIC_COLOR,
    assign_accent_hue,
    default_hue_positional,
)

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


@dataclass(frozen=True)
class BatchTopicOutcome:
    """One row's result in a `request_topics_batch` call (task 0032). Index-matched
    to the request so a partly-failed batch reports per row, not as one error."""

    request_index: int
    status: Literal["generating", "subscribed", "already_subscribed", "rejected"]
    #: Populated for "generating" / "subscribed" -- the new subscription.
    topic: TopicOut | None = None
    #: Populated for "rejected" -- the word-count rule or the name validator's
    #: specific objection, shown back on that row.
    detail: str | None = None


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

        The status lookup was a query per topic in a loop; it's one grouped
        query now rather than N+1. Currently unbounded per user (task 0024 --
        the per-user cap this used to be bounded by is gone for now), so this
        matters more than it did when it was defensive-only.
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

    async def _live_topic_ids(self, topic_ids: Sequence[UUID]) -> set[UUID]:
        """Which of `topic_ids` have crossed the "browsable" bar: at least
        `topic_live_coverage_fraction` of their subtopics have each reached
        their own `min_cards` (ADR-0053). Computed at read time against live
        card counts rather than cached on `Topic`, so it reflects reality even
        if content is later rejected/superseded, and needs no backfill for the
        existing corpus.

        Shared by `list_all`/`discover` (gates visibility for topics the
        caller doesn't already follow) and `generation_progress` (tells the
        requester's own progress view the same moment everyone else's list
        would start showing it).
        """

        if not topic_ids:
            return set()

        per_subtopic = (
            select(
                Subtopic.topic_id.label("topic_id"),
                Subtopic.id.label("subtopic_id"),
                Subtopic.min_cards.label("min_cards"),
                func.count(Card.id).filter(Card.status == CardStatus.ACTIVE).label("active_count"),
            )
            .select_from(Subtopic)
            .outerjoin(Card, Card.subtopic_id == Subtopic.id)
            .where(Subtopic.topic_id.in_(topic_ids))
            .group_by(Subtopic.topic_id, Subtopic.id, Subtopic.min_cards)
            .subquery()
        )
        coverage = select(
            per_subtopic.c.topic_id,
            func.count(per_subtopic.c.subtopic_id)
            .filter(per_subtopic.c.active_count >= per_subtopic.c.min_cards)
            .label("covered"),
            func.count(per_subtopic.c.subtopic_id).label("total"),
        ).group_by(per_subtopic.c.topic_id)

        rows = (await self._session.execute(coverage)).all()
        threshold = self._settings.topic_live_coverage_fraction
        return {
            topic_id
            for topic_id, covered, total in rows
            if total > 0 and (covered / total) >= threshold
        }

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
        live_ids = await self._live_topic_ids([topic_id])

        return GenerationProgressOut(
            status=cast(Literal["pending", "running", "completed", "failed"], job.status),
            stage=cast("Literal['curriculum', 'cards', 'done'] | None", stage),
            topic_name=cast("str | None", progress.get("topic_name")),
            subtopics=[GenerationSubtopicProgressOut(**entry) for entry in raw_subtopics],
            error=job.last_error if job.status == "failed" else None,
            topic_live=topic_id in live_ids,
        )

    async def cancel_generation(self, user_id: UUID, topic_id: UUID) -> None:
        """Cancels a still-`pending` `GenerationJob` -- the queue slot this
        user's own request created, before any worker has claimed it. Removes
        the job, the user's own subscription to it, and (if nobody else was
        already following it) the `Topic` row itself, so an abandoned request
        leaves nothing behind in the corpus or the queue.

        Guarded to `status == 'pending'` only, atomically (the `DELETE ...
        RETURNING` below either removes a still-pending row or nothing at
        all): once a worker claims the job (`pending` -> `running`), real
        quota has likely already been spent on it, and the run is a
        concurrent writer to the same row -- this refuses rather than racing
        it or trying to interrupt work already in flight.
        """

        user_topic = await self._session.scalar(
            select(UserTopic).where(
                UserTopic.user_id == user_id,
                UserTopic.topic_id == topic_id,
                UserTopic.is_custom.is_(True),
            )
        )
        if user_topic is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No custom topic request found")

        deleted_job_id = await self._session.scalar(
            delete(GenerationJob)
            .where(GenerationJob.topic_id == topic_id, GenerationJob.status == "pending")
            .returning(GenerationJob.id)
        )
        if deleted_job_id is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="Generation has already started -- can no longer be cancelled",
            )

        topic = await self._session.get(Topic, topic_id)
        if topic is not None:
            topic.subscriber_count = max(0, topic.subscriber_count - 1)

        await self._session.execute(
            delete(UserTopicProgress).where(
                UserTopicProgress.user_id == user_id, UserTopicProgress.topic_id == topic_id
            )
        )
        await self._session.execute(
            delete(UserTopic).where(UserTopic.user_id == user_id, UserTopic.topic_id == topic_id)
        )

        # Nothing was ever generated for a still-pending job (guaranteed by
        # the atomic guard above), so if this was the only follower, the
        # topic is dead weight -- clean it up rather than leaving an empty,
        # unreachable row in the corpus. `subtopics`/`aliases` cascade
        # (ondelete=CASCADE); both are already empty here regardless.
        remaining_followers = await self._session.scalar(
            select(func.count()).select_from(UserTopic).where(UserTopic.topic_id == topic_id)
        )
        if topic is not None and (remaining_followers or 0) == 0:
            await self._session.delete(topic)

        await self._session.execute(delete(FeedPlan).where(FeedPlan.user_id == user_id))
        await self._session.commit()

    async def list_all(self, user_id: UUID) -> list[TopicDiscoverOut]:
        """Every topic in the corpus, not just the top-5 unfollowed slice
        `discover` returns (ADR-0038).

        `followed` lets the client grey out Follow on a row instead of offering
        a second subscribe -- cheaper than filtering those rows out entirely,
        since "browse everything" should still show what you're already
        following. A followed topic bypasses the live-coverage filter below
        for the same reason -- you already have it, mid-generation or not.
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
        live_ids = await self._live_topic_ids([t.id for t in rows if t.id not in followed_ids])

        return [
            TopicDiscoverOut(
                topic_id=topic.id,
                display_name=topic.canonical_name,
                subscriber_count=topic.subscriber_count,
                followed=topic.id in followed_ids,
            )
            for topic in rows
            if topic.id in followed_ids or topic.id in live_ids
        ]

    async def discover(self, user_id: UUID) -> list[TopicDiscoverOut]:
        """Top N topics the user doesn't already follow, ranked by
        subscriber_count.

        The route's `mode` parameter is not threaded through: `for_you` runs the
        identical query today (ADR-0015, task 0003 — there is no signal yet to
        personalize from for topics a user hasn't subscribed to), and a
        parameter this method ignores would be a lie about what it does. The
        route keeps accepting it so the client toggle doesn't change shape.

        The `LIMIT` moves into Python (ADR-0053): a topic just past its live
        threshold can still outrank an established one on `subscriber_count`
        (a brand-new custom topic starts at 1), so the top N by subscriber
        count and the top N that are actually live aren't the same slice --
        filtering has to happen before the cut, not after a DB-side LIMIT.
        """

        followed = select(UserTopic.topic_id).where(UserTopic.user_id == user_id)
        candidates = (
            (
                await self._session.execute(
                    select(Topic)
                    .where(Topic.id.not_in(followed))
                    .order_by(Topic.subscriber_count.desc())
                )
            )
            .scalars()
            .all()
        )
        live_ids = await self._live_topic_ids([t.id for t in candidates])

        return [
            TopicDiscoverOut(
                topic_id=topic.id,
                display_name=topic.canonical_name,
                subscriber_count=topic.subscriber_count,
            )
            for topic in candidates
            if topic.id in live_ids
        ][:_DISCOVER_LIMIT]

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

    async def _assign_new_subscription_hue(
        self, user_id: UUID, topic: Topic, embedder: Embedder
    ) -> int | None:
        """ADR-0075: an embedding-apt, distinct-from-this-user's-others accent
        hue for a just-created (or being-reset) subscription. `None` when no real
        embedder is available -- the caller leaves `accent_hue` null and the
        client renders the positional default, exactly as before ADR-0075.

        The `!= topic.id` filter means this is safe to call both for a brand-new
        row and for `set_color`'s reset of an existing one. Autoflush makes rows
        added earlier in the same transaction (a `complete_onboarding` /
        `request_topics_batch` loop) visible here, so each pick dedups against
        its predecessors in the batch.
        """

        rows = (
            await self._session.execute(
                select(UserTopic.topic_id, UserTopic.accent_hue)
                .where(UserTopic.user_id == user_id, UserTopic.topic_id != topic.id)
                .order_by(UserTopic.created_at)
            )
        ).all()

        used: set[int] = set()
        for index, (other_topic_id, accent_hue) in enumerate(rows):
            if accent_hue == NO_TOPIC_COLOR:
                continue
            if accent_hue is not None:
                used.add(accent_hue % 360)
            else:
                # Legacy row the client is still rendering via its own default;
                # impute the same hue so we don't hand out a near-duplicate.
                used.add(default_hue_positional(str(other_topic_id), index))

        return await assign_accent_hue(
            embedder,
            topic_id=str(topic.id),
            topic_name=topic.canonical_name,
            topic_embedding=topic.embedding,
            used_hues=used,
            subscription_index=len(rows),
        )

    async def set_color(
        self, user_id: UUID, topic_id: UUID, hue: int | None, embedder: Embedder
    ) -> TopicOut:
        """ADR-0034: per-subscription accent hue, not a shared `Topic` property
        -- two users may color the same topic differently. `hue=-1` opts out of
        topic color entirely (ADR-0051), stored as-is.

        `hue=None` is "reset": ADR-0075 re-runs the embedding assignment (this
        topic excluded from the dedup set) and persists a fresh materialized hue,
        rather than deferring to the client's positional default. With no real
        embedder it stores `None`, and the client default applies as before."""

        user_topic = await self._session.scalar(
            select(UserTopic).where(UserTopic.user_id == user_id, UserTopic.topic_id == topic_id)
        )
        if user_topic is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not subscribed to this topic")

        progress = await self._session.scalar(
            select(UserTopicProgress).where(
                UserTopicProgress.user_id == user_id,
                UserTopicProgress.topic_id == topic_id,
            )
        )
        topic = await self._session.get(Topic, topic_id)
        assert topic is not None

        if hue is None:
            user_topic.accent_hue = await self._assign_new_subscription_hue(
                user_id, topic, embedder
            )
        else:
            user_topic.accent_hue = hue

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
        self, user_id: UUID, topic_id: UUID, entry_difficulty: Difficulty, embedder: Embedder
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
        user_topic.accent_hue = await self._assign_new_subscription_hue(user_id, topic, embedder)
        topic.subscriber_count += 1
        self._session.add(
            UserTopicProgress(
                user_id=user_id,
                topic_id=topic_id,
                current_difficulty=entry_difficulty,
                tier_unlocked=entry_tier_unlock(entry_difficulty),
            )
        )
        await self._session.execute(delete(FeedPlan).where(FeedPlan.user_id == user_id))
        await self._session.commit()

        return TopicOut(
            id=topic.id,
            display_name=user_topic.display_name,
            slug=topic.slug,
            is_custom=False,
            current_difficulty=entry_difficulty,
            accent_hue=user_topic.accent_hue,
        )

    async def unsubscribe(self, user_id: UUID, topic_id: UUID) -> None:
        """Drops the `UserTopic` row and its progress. Engagement history
        (likes/saves/notes) is left alone -- it's the user's own record of
        having read those cards, not membership state -- and the feed's
        cached plan is cleared so a re-follow doesn't serve a stale mix."""

        user_topic = await self._session.scalar(
            select(UserTopic).where(UserTopic.user_id == user_id, UserTopic.topic_id == topic_id)
        )
        if user_topic is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not subscribed to this topic")

        topic = await self._session.get(Topic, topic_id)
        if topic is not None:
            topic.subscriber_count = max(0, topic.subscriber_count - 1)

        await self._session.execute(
            delete(UserTopicProgress).where(
                UserTopicProgress.user_id == user_id, UserTopicProgress.topic_id == topic_id
            )
        )
        await self._session.execute(
            delete(UserTopic).where(UserTopic.user_id == user_id, UserTopic.topic_id == topic_id)
        )
        await self._session.execute(delete(FeedPlan).where(FeedPlan.user_id == user_id))
        await self._session.commit()

    async def complete_onboarding(
        self, user_id: UUID, choices: list[OnboardingTopicChoice], embedder: Embedder
    ) -> list[TopicOut]:
        """First-run setup: subscribe to the chosen topics, each at its own
        entry tier, then flip the gate the root route checks. Unknown IDs are
        skipped rather than failing the whole request -- onboarding should not
        strand a user over one stale entry in the picker's list.

        Each row's ADR-0075 accent hue is assigned in sequence, so the second
        topic dedups against the first, the third against both, and so on."""

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
            user_topic.accent_hue = await self._assign_new_subscription_hue(
                user_id, topic, embedder
            )
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
                    accent_hue=user_topic.accent_hue,
                )
            )

        user = await self._session.get(User, user_id)
        assert user is not None
        user.onboarding_complete = True

        await self._session.execute(delete(FeedPlan).where(FeedPlan.user_id == user_id))
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
        ephemeral, so letting it trigger a real generation job has no durable
        payoff and is easy to abuse anonymously. (The per-user count limit
        that used to sit alongside this is gone for now -- see task 0024.)

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
        user_topic.accent_hue = await self._assign_new_subscription_hue(user_id, topic, embedder)
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

        await session.execute(delete(FeedPlan).where(FeedPlan.user_id == user_id))
        await session.commit()

        return RequestedTopic(
            topic=TopicOut(
                id=topic.id,
                display_name=user_topic.display_name,
                slug=topic.slug,
                is_custom=True,
                current_difficulty=entry_difficulty,
                accent_hue=user_topic.accent_hue,
            ),
            status="generating" if is_new_topic else "subscribed",
        )

    async def request_topics_batch(
        self,
        user_id: UUID,
        *,
        items: Sequence[TopicRequestIn],
        generator: ContentGenerator,
        embedder: Embedder,
    ) -> list[BatchTopicOutcome]:
        """The batched form of `request_topic` (task 0032, ADR-0025).

        Every name is word-count-checked in code (a constraint, not taste),
        then the survivors go through ONE `validate_topic_names` call and ONE
        `match_and_create_topics` call -- two LLM requests for the whole batch,
        not two per item (ADR-0005: the free tier meters requests). One
        `FeedPlan` clear and one commit cover every row.

        Partial success is the normal case: a name rejected by the validator,
        a topic the user already follows, and a freshly-minted one can all
        come back from the same call, each as its own `BatchTopicOutcome`.
        """

        settings = self._settings
        session = self._session

        user = await session.get(User, user_id)
        assert user is not None
        if user.is_guest:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, detail="Sign up to request a custom topic"
            )

        outcomes: dict[int, BatchTopicOutcome] = {}

        # Code-level name checks. Rows that fail are rejected here and never
        # reach an LLM call; `clean` holds the stripped name for the rest.
        clean: dict[int, str] = {}
        for index, item in enumerate(items):
            name = item.name.strip()
            if not name:
                outcomes[index] = BatchTopicOutcome(
                    index, "rejected", detail="Topic name is required"
                )
                continue
            if len(name.split()) > settings.custom_topic_max_words:
                outcomes[index] = BatchTopicOutcome(
                    index,
                    "rejected",
                    detail=f"Keep it short -- {settings.custom_topic_max_words} words or fewer",
                )
                continue
            clean[index] = name

        # ONE name-validation call over every surviving row.
        if clean:
            verdicts = await generator.validate_topic_names(
                [TopicNameQuery(request_index=i, name=n) for i, n in clean.items()]
            )
            verdict_by_index = {v.request_index: v for v in verdicts.items}
            for index in list(clean):
                verdict = verdict_by_index.get(index)
                if verdict is not None and not verdict.acceptable:
                    outcomes[index] = BatchTopicOutcome(
                        index,
                        "rejected",
                        detail=verdict.reason or "That doesn't look like a learnable topic",
                    )
                    del clean[index]

        # ONE match/create call over every validated row. `match_and_create_topics`
        # returns outcomes in the order it was given the requests.
        validated = list(clean)
        if validated:
            match_outcomes = await match_and_create_topics(
                session,
                generator,
                embedder,
                settings,
                topic_requests=[
                    TopicRequest(name=clean[i], description=(items[i].description or "").strip())
                    for i in validated
                ],
            )

            feed_plan_dirty = False
            for index, match in zip(validated, match_outcomes, strict=True):
                item = items[index]
                topic_id = UUID(match["topic_id"])

                existing = await session.scalar(
                    select(UserTopic).where(
                        UserTopic.user_id == user_id, UserTopic.topic_id == topic_id
                    )
                )
                if existing is not None:
                    # Already following the topic this name resolved to -- no
                    # slot spent, no job. Any alias row the matcher just wrote
                    # is still committed by the single commit below.
                    outcomes[index] = BatchTopicOutcome(index, "already_subscribed")
                    continue

                topic = await session.get(Topic, topic_id)
                assert topic is not None

                user_topic = UserTopic(
                    user_id=user_id,
                    topic_id=topic_id,
                    display_name=clean[index],
                    is_custom=True,
                )
                session.add(user_topic)
                user_topic.accent_hue = await self._assign_new_subscription_hue(
                    user_id, topic, embedder
                )
                topic.subscriber_count += 1
                session.add(
                    UserTopicProgress(
                        user_id=user_id,
                        topic_id=topic_id,
                        current_difficulty=item.entry_difficulty,
                        tier_unlocked=entry_tier_unlock(item.entry_difficulty),
                    )
                )

                is_new_topic = not match["matched_existing"]
                if is_new_topic:
                    session.add(GenerationJob(topic_id=topic_id, status="pending"))
                feed_plan_dirty = True

                outcomes[index] = BatchTopicOutcome(
                    index,
                    "generating" if is_new_topic else "subscribed",
                    topic=TopicOut(
                        id=topic.id,
                        display_name=user_topic.display_name,
                        slug=topic.slug,
                        is_custom=True,
                        current_difficulty=item.entry_difficulty,
                        accent_hue=user_topic.accent_hue,
                    ),
                )

            if feed_plan_dirty:
                await session.execute(delete(FeedPlan).where(FeedPlan.user_id == user_id))

        await session.commit()
        return [outcomes[index] for index in range(len(items))]
