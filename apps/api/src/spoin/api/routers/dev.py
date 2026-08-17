"""Dev-only convenience endpoints.

**Not for production.** `/dev/reset` mutates a user's entire progress and
subscription state on a single call gated by nothing but the placeholder
`X-User-Id` auth every other endpoint already has (deps.py's own docstring
flags that as needing real auth before anything is exposed publicly) — fine
for repeatedly exercising a local demo account, not something a real
deployment should expose. Gate or remove this router before that.
"""

from __future__ import annotations

import random

from fastapi import APIRouter
from sqlalchemy import delete, select

from spoin.api.deps import SessionDep, UserDep
from spoin.api.schemas import TopicOut
from spoin.domain.enums import Difficulty
from spoin.domain.models import (
    FeedPlan,
    FeedSlate,
    Topic,
    UserCardState,
    UserTopic,
    UserTopicProgress,
)

router = APIRouter(prefix="/dev", tags=["dev"])

#: How many followed topics get sent back to Discover on each reset.
_UNFOLLOW_COUNT = 2


@router.post("/reset", response_model=list[TopicOut])
async def reset_demo(session: SessionDep, user_id: UserDep) -> list[TopicOut]:
    """Fresh-demo state, for exercising the app repeatedly without a database
    reset:

    - Every card's seen-state is cleared (coverage goes back to 0%).
    - The feed's pagination cursor is cleared, so the mixed feed stops
      reporting "exhausted" from a prior session's testing.
    - Every followed topic's progress resets to beginner/nothing-unlocked.
    - `_UNFOLLOW_COUNT` randomly-chosen followed topics are unfollowed, so
      they reappear in Discover instead of staying permanently subscribed.
    """

    await session.execute(delete(UserCardState).where(UserCardState.user_id == user_id))
    await session.execute(delete(FeedSlate).where(FeedSlate.user_id == user_id))
    await session.execute(delete(FeedPlan).where(FeedPlan.user_id == user_id))

    progress_rows = (
        await session.execute(select(UserTopicProgress).where(UserTopicProgress.user_id == user_id))
    ).scalars().all()
    for progress in progress_rows:
        progress.current_difficulty = Difficulty.BEGINNER
        progress.tier_unlocked = [False, False, False]
        progress.tier_content_complete = [False, False, False]
        progress.tier_quiz_passed = [False, False, False]
        progress.mastered_at = None
        progress.revisit_mode = False

    followed_topic_ids = (
        await session.execute(select(UserTopic.topic_id).where(UserTopic.user_id == user_id))
    ).scalars().all()
    to_unfollow = random.sample(followed_topic_ids, k=min(_UNFOLLOW_COUNT, len(followed_topic_ids)))
    for topic_id in to_unfollow:
        await session.execute(
            delete(UserTopic).where(UserTopic.user_id == user_id, UserTopic.topic_id == topic_id)
        )
        await session.execute(
            delete(UserTopicProgress).where(
                UserTopicProgress.user_id == user_id, UserTopicProgress.topic_id == topic_id
            )
        )

    await session.commit()

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
            display_name=user_topic.display_name,
            slug=topic.slug,
            is_custom=user_topic.is_custom,
            current_difficulty=tier or Difficulty.BEGINNER,
        )
        for user_topic, topic, tier in rows
    ]
