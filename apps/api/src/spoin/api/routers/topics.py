"""Topic subscriptions and progress."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from spoin.api.deps import SessionDep, UserDep
from spoin.api.schemas import (
    CustomTopicStatusOut,
    OnboardingCompleteIn,
    ProgressOut,
    SubtopicProgressOut,
    TopicColorIn,
    TopicCurriculumOut,
    TopicDiscoverOut,
    TopicOut,
    TopicRequestIn,
    TopicRequestOut,
    TopicStatsOut,
)
from spoin.core.config import get_settings
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
from spoin.embeddings import get_embedder
from spoin.generation import get_content_generator
from spoin.generation.base import TopicNameQuery
from spoin.generation.pipeline import TopicRequest, match_and_create_topics

#: Notes/shares have no mutable-state table (ADR-0015) — these are the only two
#: kinds `/topics/{id}/stats` aggregates from the raw event log rather than a
#: current-state count.
_STATS_EVENT_KINDS = (EngagementKind.NOTE, EngagementKind.SHARE)

router = APIRouter(prefix="/topics", tags=["topics"])

#: The coverage gate (ADR-0009). Relative rather than absolute so it self-adjusts
#: to whatever the corpus actually holds — a thin subtopic cannot strand a user at
#: an unreachable bar.
COVERAGE_GATE = 0.80

#: content-model.md's "Custom topics" section. Enforced here, server-side, on
#: `UserTopic.is_custom` rows -- a custom topic that canonicalizes onto an
#: existing topic still consumes a slot (ADR-0004): users are buying slots in
#: their own topic list, not new entries in the shared corpus.
CUSTOM_TOPIC_LIMIT = 3

#: A constraint, not taste -- enforced here in code rather than asked of the
#: model, per the "generator is trusted for taste, never for constraints"
#: rule. Keeps the box a topic name, not a sentence describing one.
CUSTOM_TOPIC_MAX_WORDS = 5


def _entry_tier_unlock(entry: Difficulty) -> list[bool]:
    """ADR-0032 (amends ADR-0027): only tiers STRICTLY BELOW the chosen entry
    tier start pre-unlocked, as unlimited practice -- trusted unconditionally,
    same as before. The entry tier itself is never free: it still earns its
    own quiz through the normal 80% coverage gate, exactly like every other
    tier (see `_progress_snapshot`). A Beginner entry therefore starts fully
    locked, same as a user who was promoted there the hard way -- there is
    nothing below Beginner to trust for free."""

    return [rank < entry.rank for rank in range(len(Difficulty))]


@router.post("", response_model=TopicRequestOut, status_code=status.HTTP_201_CREATED)
async def request_topic(
    payload: TopicRequestIn, session: SessionDep, user_id: UserDep
) -> TopicRequestOut:
    """A user typing a topic name, as opposed to picking one from Discover.

    Runs the name through ADR-0025's batched matcher: a match onto an existing
    topic just subscribes the user (no generation triggered here). A genuine
    miss mints a new `Topic` row and enqueues a `GenerationJob` -- generation
    is never synchronous (ADR-0003), so the response reports which case
    happened rather than returning cards.

    Custom topics are gated to non-guest users -- a guest's account is
    ephemeral, so letting it spend one of the three custom-topic slots (and
    trigger a real generation job) has no durable payoff and is easy to abuse
    anonymously. Signing up (or signing back in) is what unlocks this.
    """

    user = await session.get(User, user_id)
    assert user is not None
    if user.is_guest:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="Sign up to request a custom topic"
        )

    name = payload.name.strip()
    if not name:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Topic name is required")
    if len(name.split()) > CUSTOM_TOPIC_MAX_WORDS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Keep it short -- {CUSTOM_TOPIC_MAX_WORDS} words or fewer",
        )

    verdicts = await get_content_generator().validate_topic_names(
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
    if (custom_count or 0) >= CUSTOM_TOPIC_LIMIT:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail=f"Custom topic limit reached ({CUSTOM_TOPIC_LIMIT})",
        )

    outcomes = await match_and_create_topics(
        session,
        get_content_generator(),
        get_embedder(),
        get_settings(),
        topic_requests=[TopicRequest(name=name, description=(payload.description or "").strip())],
    )
    outcome = outcomes[0]
    topic_id = UUID(outcome["topic_id"])

    existing = await session.scalar(
        select(UserTopic).where(UserTopic.user_id == user_id, UserTopic.topic_id == topic_id)
    )
    if existing is not None:
        # Already following the topic this name resolved to -- no slot spent,
        # no second job. Whatever match_and_create_topics did above (at most
        # a new alias row) is still worth keeping, so commit rather than
        # rolling back.
        await session.commit()
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Already subscribed")

    topic = await session.get(Topic, topic_id)
    assert topic is not None

    # The user's own label, same as subscribe_topic -- but here it's what
    # they actually typed, not the canonical name they picked from a list.
    user_topic = UserTopic(user_id=user_id, topic_id=topic_id, display_name=name, is_custom=True)
    session.add(user_topic)
    topic.subscriber_count += 1
    session.add(
        UserTopicProgress(
            user_id=user_id,
            topic_id=topic_id,
            current_difficulty=payload.entry_difficulty,
            tier_unlocked=_entry_tier_unlock(payload.entry_difficulty),
        )
    )

    is_new_topic = not outcome["matched_existing"]
    if is_new_topic:
        session.add(GenerationJob(topic_id=topic_id, status="pending"))

    await session.commit()

    return TopicRequestOut(
        topic=TopicOut(
            id=topic.id,
            display_name=user_topic.display_name,
            slug=topic.slug,
            is_custom=True,
            current_difficulty=payload.entry_difficulty,
        ),
        status="generating" if is_new_topic else "subscribed",
    )


@router.get("", response_model=list[TopicOut])
async def list_topics(session: SessionDep, user_id: UserDep) -> list[TopicOut]:
    rows = (
        await session.execute(
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


@router.get("/custom", response_model=list[CustomTopicStatusOut])
async def list_custom_topics(session: SessionDep, user_id: UserDep) -> list[CustomTopicStatusOut]:
    """This user's custom (self-requested) topics, each with its most recent
    `GenerationJob` status -- the piece item 6/dsa-style confusion is missing
    today: a user has no way to tell "still generating" from "broken" from
    "nothing was ever queued" for a topic they typed in themselves.

    A topic can in principle have more than one `GenerationJob` row over its
    lifetime (retried failures, say) even though at most one is ever
    pending/running at once (the model's coalescing index) -- so this reads
    the latest by `created_at`, not an unqualified join.
    """

    rows = (
        await session.execute(
            select(UserTopic, Topic)
            .join(Topic, Topic.id == UserTopic.topic_id)
            .where(UserTopic.user_id == user_id, UserTopic.is_custom.is_(True))
            .order_by(UserTopic.created_at)
        )
    ).all()

    result: list[CustomTopicStatusOut] = []
    for user_topic, topic in rows:
        latest_job = await session.scalar(
            select(GenerationJob)
            .where(GenerationJob.topic_id == topic.id)
            .order_by(GenerationJob.created_at.desc())
            .limit(1)
        )
        result.append(
            CustomTopicStatusOut(
                topic_id=topic.id,
                display_name=user_topic.display_name,
                slug=topic.slug,
                generation_status=latest_job.status if latest_job else None,
                requested_at=user_topic.created_at,
            )
        )
    return result


@router.patch("/{topic_id}/color", response_model=TopicOut)
async def set_topic_color(
    topic_id: UUID, payload: TopicColorIn, session: SessionDep, user_id: UserDep
) -> TopicOut:
    """ADR-0034: per-subscription accent hue, not a shared `Topic` property --
    two users may color the same topic differently. `hue=null` resets to the
    deterministic default the client computes itself, so this only ever needs
    to be called for an explicit override."""

    user_topic = await session.scalar(
        select(UserTopic).where(UserTopic.user_id == user_id, UserTopic.topic_id == topic_id)
    )
    if user_topic is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not subscribed to this topic")

    user_topic.accent_hue = payload.hue
    progress = await session.scalar(
        select(UserTopicProgress).where(
            UserTopicProgress.user_id == user_id, UserTopicProgress.topic_id == topic_id
        )
    )
    topic = await session.get(Topic, topic_id)
    assert topic is not None
    await session.commit()

    return TopicOut(
        id=topic.id,
        display_name=user_topic.display_name,
        slug=topic.slug,
        is_custom=user_topic.is_custom,
        current_difficulty=progress.current_difficulty if progress else Difficulty.BEGINNER,
        accent_hue=user_topic.accent_hue,
    )


@router.get("/all", response_model=list[TopicDiscoverOut])
async def list_all_topics(session: SessionDep, user_id: UserDep) -> list[TopicDiscoverOut]:
    """Every topic in the corpus, not just the top-5 unfollowed slice
    `/topics/discover` returns (ADR-0038: the modal's "Topics" tab is meant
    to be the actual browse-everything surface now that the always-visible
    inline Discover box already covers the fast "what's new" glance).

    `followed` lets the client grey out Follow on a row instead of offering a
    second subscribe -- cheaper than filtering those rows out entirely, since
    "browse everything" should still show what you're already following.
    """

    followed_ids = set(
        (
            await session.execute(
                select(UserTopic.topic_id).where(UserTopic.user_id == user_id)
            )
        )
        .scalars()
        .all()
    )

    rows = (
        await session.execute(select(Topic).order_by(Topic.subscriber_count.desc()))
    ).scalars().all()

    return [
        TopicDiscoverOut(
            topic_id=topic.id,
            display_name=topic.canonical_name,
            subscriber_count=topic.subscriber_count,
            followed=topic.id in followed_ids,
        )
        for topic in rows
    ]


@router.get("/discover", response_model=list[TopicDiscoverOut])
async def discover_topics(
    session: SessionDep, user_id: UserDep, mode: str = "popular"
) -> list[TopicDiscoverOut]:
    """Top 5 topics the user doesn't already follow, ranked by subscriber_count.

    `mode` is accepted but `for_you` runs the identical query for now — there is
    no signal yet to personalize from for topics a user hasn't subscribed to
    (see ADR-0015, task 0003). The parameter exists so the frontend toggle and
    this route don't need to change shape once that work lands.
    """
    del mode  # Both modes share one query today; kept as a real branch point.

    followed = select(UserTopic.topic_id).where(UserTopic.user_id == user_id)
    rows = (
        await session.execute(
            select(Topic)
            .where(Topic.id.not_in(followed))
            .order_by(Topic.subscriber_count.desc())
            .limit(5)
        )
    ).scalars().all()

    return [
        TopicDiscoverOut(
            topic_id=topic.id,
            display_name=topic.canonical_name,
            subscriber_count=topic.subscriber_count,
        )
        for topic in rows
    ]


@router.post("/{topic_id}/subscribe", response_model=TopicOut, status_code=status.HTTP_201_CREATED)
async def subscribe_topic(
    topic_id: UUID,
    session: SessionDep,
    user_id: UserDep,
    entry_difficulty: Difficulty = Difficulty.BEGINNER,
) -> TopicOut:
    topic = await session.get(Topic, topic_id)
    if topic is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Unknown topic")

    existing = await session.scalar(
        select(UserTopic).where(UserTopic.user_id == user_id, UserTopic.topic_id == topic_id)
    )
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Already subscribed")

    # No rename UI exists yet (ADR-0004's personal-label split), so the label
    # starts as the canonical name — same default seed.py uses.
    user_topic = UserTopic(
        user_id=user_id, topic_id=topic_id, display_name=topic.canonical_name, is_custom=False
    )
    session.add(user_topic)
    topic.subscriber_count += 1
    # ADR-0027, amended by ADR-0032: tiers below the chosen entry tier start
    # unlocked for practice, trusted unconditionally. The entry tier itself
    # still earns its quiz through the normal coverage gate.
    session.add(
        UserTopicProgress(
            user_id=user_id,
            topic_id=topic_id,
            current_difficulty=entry_difficulty,
            tier_unlocked=_entry_tier_unlock(entry_difficulty),
        )
    )
    await session.commit()

    return TopicOut(
        id=topic.id,
        display_name=user_topic.display_name,
        slug=topic.slug,
        is_custom=False,
        current_difficulty=entry_difficulty,
    )


@router.post("/onboarding/complete", response_model=list[TopicOut])
async def complete_onboarding(
    payload: OnboardingCompleteIn, session: SessionDep, user_id: UserDep
) -> list[TopicOut]:
    """First-run setup: subscribe to the chosen topics, each at its own entry
    tier, then flip the gate the root route checks (see docs/adr on
    auth/onboarding). Unknown IDs are skipped rather than failing the whole
    request -- onboarding should not strand a user over one stale entry in
    the picker's list."""
    subscribed: list[TopicOut] = []
    for choice in payload.topics:
        topic = await session.get(Topic, choice.topic_id)
        if topic is None:
            continue

        existing = await session.scalar(
            select(UserTopic).where(UserTopic.user_id == user_id, UserTopic.topic_id == topic.id)
        )
        if existing is not None:
            continue

        user_topic = UserTopic(
            user_id=user_id,
            topic_id=topic.id,
            display_name=topic.canonical_name,
            is_custom=False,
        )
        session.add(user_topic)
        topic.subscriber_count += 1
        session.add(
            UserTopicProgress(
                user_id=user_id,
                topic_id=topic.id,
                current_difficulty=choice.entry_difficulty,
                tier_unlocked=_entry_tier_unlock(choice.entry_difficulty),
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

    user = await session.get(User, user_id)
    assert user is not None
    user.onboarding_complete = True

    await session.commit()
    return subscribed


@router.get("/{topic_id}/stats", response_model=TopicStatsOut)
async def get_topic_stats(topic_id: UUID, session: SessionDep, user_id: UserDep) -> TopicStatsOut:
    tier, coverage, unlocked, mastered = await _progress_snapshot(session, user_id, topic_id)

    progress = await session.scalar(
        select(UserTopicProgress).where(
            UserTopicProgress.user_id == user_id, UserTopicProgress.topic_id == topic_id
        )
    )

    likes = await session.scalar(
        select(func.count())
        .select_from(CardLike)
        .join(Card, Card.id == CardLike.card_id)
        .where(CardLike.user_id == user_id, Card.topic_id == topic_id)
    )
    saves = await session.scalar(
        select(func.count())
        .select_from(CardBookmark)
        .join(Card, Card.id == CardBookmark.card_id)
        .where(CardBookmark.user_id == user_id, Card.topic_id == topic_id)
    )

    event_rows = (
        await session.execute(
            select(EngagementEvent.kind, func.count())
            .where(
                EngagementEvent.user_id == user_id,
                EngagementEvent.topic_id == topic_id,
                EngagementEvent.kind.in_(_STATS_EVENT_KINDS),
            )
            .group_by(EngagementEvent.kind)
        )
    ).all()
    event_counts = {kind: count for kind, count in event_rows}

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


@router.get("/{topic_id}/curriculum", response_model=TopicCurriculumOut)
async def get_topic_curriculum(
    topic_id: UUID, session: SessionDep, user_id: UserDep
) -> TopicCurriculumOut:
    """Every subtopic across all three tiers, with this user's per-subtopic
    coverage — the detail TopicStatsModal's aggregate numbers are rolled up
    from. Ordered by difficulty then `position`, matching curriculum-authoring
    order (content-model.md), not insertion order.
    """

    rows = (
        await session.execute(
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

    subtopics = [
        SubtopicProgressOut(
            subtopic_id=subtopic_id,
            title=title,
            difficulty=difficulty,
            total_cards=total,
            seen_cards=seen,
            coverage=(seen / total) if total else 0.0,
            # Same gate `_tier_coverage` uses for tier unlock: seen/total >=
            # COVERAGE_GATE, applied here per subtopic instead of only at the
            # thinnest one.
            covered=(total > 0 and seen / total >= COVERAGE_GATE),
        )
        for subtopic_id, title, difficulty, total, seen in rows
    ]

    return TopicCurriculumOut(topic_id=topic_id, subtopics=subtopics)


@router.get("/{topic_id}/progress", response_model=ProgressOut)
async def get_progress(topic_id: UUID, session: SessionDep, user_id: UserDep) -> ProgressOut:
    progress, tier, coverage, unlocked, mastered = await ensure_unlock_latched(
        session, user_id, topic_id
    )

    return ProgressOut(
        topic_id=topic_id,
        current_difficulty=tier,
        coverage=coverage,
        quiz_unlocked=unlocked,
        tier_quiz_passed=list(progress.tier_quiz_passed) if progress else [False] * 3,
        mastered=mastered,
    )


async def ensure_unlock_latched(
    session: SessionDep, user_id: UUID, topic_id: UUID
) -> tuple[UserTopicProgress | None, Difficulty, float, bool, bool]:
    """Read the coverage snapshot, then write the tier_unlocked latch if newly
    earned. Shared by `get_progress` and quiz.py's start-quiz check, so both
    agree on what's unlocked without duplicating the write.

    The latch itself: once unlocked, it stays unlocked. Recomputing would let
    background generation revoke earned progress, dropping a user from 8/10
    (80%, unlocked) to 8/20 (40%, locked) the moment ten more cards land.
    """

    tier, coverage, unlocked, mastered = await _progress_snapshot(session, user_id, topic_id)
    progress = await session.scalar(
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
        await session.commit()
    return progress, tier, coverage, unlocked, mastered


async def _progress_snapshot(
    session: SessionDep, user_id: UUID, topic_id: UUID
) -> tuple[Difficulty, float, bool, bool]:
    """Read-only version of `get_progress`'s lookup: tier, coverage, unlocked, mastered.

    Split out so a future read-only caller (a stats/insights view, say) can
    reuse this without also triggering `get_progress`'s latch write.
    """

    progress = await session.scalar(
        select(UserTopicProgress).where(
            UserTopicProgress.user_id == user_id,
            UserTopicProgress.topic_id == topic_id,
        )
    )
    tier = progress.current_difficulty if progress else Difficulty.BEGINNER
    coverage = await _tier_coverage(session, user_id, topic_id, tier)
    already_unlocked = bool(progress and progress.tier_unlocked[tier.rank])
    unlocked = already_unlocked or coverage >= COVERAGE_GATE
    mastered = bool(progress and progress.mastered_at is not None)
    return tier, coverage, unlocked, mastered


async def _tier_coverage(
    session: SessionDep, user_id: UUID, topic_id: UUID, tier: Difficulty
) -> float:
    """Coverage of the **weakest** subtopic in the tier.

    The gate is "80% of the cards in EVERY subtopic", so the thinnest one governs.
    Averaging across subtopics would let a user coast on one well-read subtopic
    while never opening another.
    """

    rows = (
        await session.execute(
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
