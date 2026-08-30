"""Topic subscriptions and progress: HTTP surface only.

All 48 SQL statements, the custom-topic quota, the name-validation LLM call and
the tier-progression latch moved to `spoin.topics.service`. These handlers
parse, delegate, and serialize.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from spoin.api.deps import SessionDep, UserDep
from spoin.api.schemas import (
    CustomTopicStatusOut,
    GenerationProgressOut,
    OnboardingCompleteIn,
    ProgressOut,
    TopicBatchIn,
    TopicBatchItemOut,
    TopicBatchOut,
    TopicColorIn,
    TopicCurriculumOut,
    TopicDiscoverOut,
    TopicOut,
    TopicRequestIn,
    TopicRequestOut,
    TopicStatsOut,
)
from spoin.core.config import get_settings
from spoin.domain.enums import Difficulty
from spoin.embeddings import get_embedder
from spoin.generation import get_content_generator
from spoin.topics.service import TopicsService

router = APIRouter(prefix="/topics", tags=["topics"])


def _service(session: SessionDep) -> TopicsService:
    return TopicsService(session, get_settings())


@router.post("", response_model=TopicRequestOut, status_code=status.HTTP_201_CREATED)
async def request_topic(
    payload: TopicRequestIn, session: SessionDep, user_id: UserDep
) -> TopicRequestOut:
    requested = await _service(session).request_topic(
        user_id,
        name=payload.name,
        description=payload.description or "",
        entry_difficulty=payload.entry_difficulty,
        generator=get_content_generator(),
        embedder=get_embedder(),
    )
    return TopicRequestOut(topic=requested.topic, status=requested.status)


@router.post("/batch", response_model=TopicBatchOut, status_code=status.HTTP_201_CREATED)
async def request_topics_batch(
    payload: TopicBatchIn, session: SessionDep, user_id: UserDep
) -> TopicBatchOut:
    """Several custom topics in one submission (task 0032). Runs ADR-0025's
    batched matcher once for the whole list; each row reports its own outcome,
    so a batch where some rows are rejected is still a 201 with per-row detail,
    not a failure for the whole call."""

    outcomes = await _service(session).request_topics_batch(
        user_id,
        items=payload.items,
        generator=get_content_generator(),
        embedder=get_embedder(),
    )
    return TopicBatchOut(
        results=[
            TopicBatchItemOut(
                request_index=o.request_index,
                status=o.status,
                topic=o.topic,
                detail=o.detail,
            )
            for o in outcomes
        ]
    )


@router.get("", response_model=list[TopicOut])
async def list_topics(session: SessionDep, user_id: UserDep) -> list[TopicOut]:
    return await _service(session).list_subscribed(user_id)


@router.get("/custom", response_model=list[CustomTopicStatusOut])
async def list_custom_topics(session: SessionDep, user_id: UserDep) -> list[CustomTopicStatusOut]:
    return await _service(session).list_custom(user_id)


@router.get("/{topic_id}/generation-progress", response_model=GenerationProgressOut)
async def generation_progress(
    topic_id: UUID, session: SessionDep, user_id: UserDep
) -> GenerationProgressOut:
    return await _service(session).generation_progress(topic_id)


@router.delete("/{topic_id}/generation-job", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_generation(topic_id: UUID, session: SessionDep, user_id: UserDep) -> None:
    await _service(session).cancel_generation(user_id, topic_id)


@router.patch("/{topic_id}/color", response_model=TopicOut)
async def set_topic_color(
    topic_id: UUID, payload: TopicColorIn, session: SessionDep, user_id: UserDep
) -> TopicOut:
    return await _service(session).set_color(user_id, topic_id, payload.hue, get_embedder())


@router.get("/all", response_model=list[TopicDiscoverOut])
async def list_all_topics(session: SessionDep, user_id: UserDep) -> list[TopicDiscoverOut]:
    return await _service(session).list_all(user_id)


@router.get("/discover", response_model=list[TopicDiscoverOut])
async def discover_topics(
    session: SessionDep, user_id: UserDep, mode: str = "popular"
) -> list[TopicDiscoverOut]:
    """`mode` is accepted but unused: `for_you` runs the identical query today
    (ADR-0015, task 0003). The parameter stays so the client toggle and this
    route don't need to change shape once that work lands."""

    del mode
    return await _service(session).discover(user_id)


@router.post("/{topic_id}/subscribe", response_model=TopicOut, status_code=status.HTTP_201_CREATED)
async def subscribe_topic(
    topic_id: UUID,
    session: SessionDep,
    user_id: UserDep,
    entry_difficulty: Difficulty = Difficulty.BEGINNER,
) -> TopicOut:
    return await _service(session).subscribe(user_id, topic_id, entry_difficulty, get_embedder())


@router.delete("/{topic_id}/subscribe", status_code=status.HTTP_204_NO_CONTENT)
async def unsubscribe_topic(topic_id: UUID, session: SessionDep, user_id: UserDep) -> None:
    await _service(session).unsubscribe(user_id, topic_id)


@router.post("/onboarding/complete", response_model=list[TopicOut])
async def complete_onboarding(
    payload: OnboardingCompleteIn, session: SessionDep, user_id: UserDep
) -> list[TopicOut]:
    return await _service(session).complete_onboarding(user_id, payload.topics, get_embedder())


@router.get("/{topic_id}/stats", response_model=TopicStatsOut)
async def get_topic_stats(topic_id: UUID, session: SessionDep, user_id: UserDep) -> TopicStatsOut:
    return await _service(session).stats(user_id, topic_id)


@router.get("/{topic_id}/curriculum", response_model=TopicCurriculumOut)
async def get_topic_curriculum(
    topic_id: UUID, session: SessionDep, user_id: UserDep
) -> TopicCurriculumOut:
    return await _service(session).curriculum(user_id, topic_id)


@router.get("/{topic_id}/progress", response_model=ProgressOut)
async def get_progress(topic_id: UUID, session: SessionDep, user_id: UserDep) -> ProgressOut:
    return await _service(session).progress(user_id, topic_id)
