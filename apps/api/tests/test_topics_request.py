"""POST /topics — a user requesting a topic by name (task 0011, part 1).

Uses the real `session` fixture (Postgres + pgvector, skipped if unavailable) since
topic matching needs real cosine-distance queries. `get_content_generator`/
`get_embedder` default to the fake/hash backends (no env vars set here), so this
never touches the network.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from spoin.api.routers.topics import request_topic
from spoin.api.schemas import TopicRequestIn
from spoin.core.config import get_settings
from spoin.domain.models import GenerationJob, User, UserTopic


async def _make_user(session: AsyncSession) -> uuid.UUID:
    user = User(email=f"{uuid.uuid4()}@test.local", display_name="Test")
    session.add(user)
    await session.flush()
    return user.id


async def test_new_topic_mints_topic_subscribes_and_enqueues_job(session: AsyncSession) -> None:
    user_id = await _make_user(session)

    result = await request_topic(TopicRequestIn(name="Photosynthesis"), session, user_id)

    assert result.status == "generating"
    assert result.topic.display_name == "Photosynthesis"
    assert result.topic.is_custom is True

    user_topic = await session.scalar(
        select(UserTopic).where(UserTopic.user_id == user_id, UserTopic.topic_id == result.topic.id)
    )
    assert user_topic is not None
    assert user_topic.is_custom is True

    job = await session.scalar(
        select(GenerationJob).where(GenerationJob.topic_id == result.topic.id)
    )
    assert job is not None
    assert job.status == "pending"


async def test_matching_existing_topic_subscribes_without_a_job(session: AsyncSession) -> None:
    user_id = await _make_user(session)
    other_user_id = await _make_user(session)

    # First request mints the topic (no one else follows it yet).
    first = await request_topic(TopicRequestIn(name="Thermodynamics"), session, other_user_id)
    assert first.status == "generating"

    # A second user typing a near-identical name should match onto it rather
    # than minting a duplicate Topic row or a second GenerationJob.
    second = await request_topic(TopicRequestIn(name="thermodynamics"), session, user_id)

    assert second.topic.id == first.topic.id
    assert second.status == "subscribed"

    jobs = (
        (await session.execute(select(GenerationJob).where(GenerationJob.topic_id == first.topic.id)))
        .scalars()
        .all()
    )
    assert len(jobs) == 1


async def test_already_subscribed_is_a_conflict(session: AsyncSession) -> None:
    user_id = await _make_user(session)

    first = await request_topic(TopicRequestIn(name="Entropy"), session, user_id)
    assert first.status == "generating"

    with pytest.raises(HTTPException) as exc_info:
        await request_topic(TopicRequestIn(name="Entropy"), session, user_id)
    assert exc_info.value.status_code == 409


async def test_custom_topic_limit_enforced_server_side(session: AsyncSession) -> None:
    user_id = await _make_user(session)

    for index in range(get_settings().custom_topic_limit):
        result = await request_topic(TopicRequestIn(name=f"Topic {index}"), session, user_id)
        assert result.topic.is_custom is True

    custom_count = await session.scalar(
        select(func.count())
        .select_from(UserTopic)
        .where(UserTopic.user_id == user_id, UserTopic.is_custom.is_(True))
    )
    assert custom_count == get_settings().custom_topic_limit

    with pytest.raises(HTTPException) as exc_info:
        await request_topic(TopicRequestIn(name="One too many"), session, user_id)
    assert exc_info.value.status_code == 403


async def test_blank_name_rejected(session: AsyncSession) -> None:
    user_id = await _make_user(session)

    with pytest.raises(HTTPException) as exc_info:
        await request_topic(TopicRequestIn(name="   "), session, user_id)
    assert exc_info.value.status_code == 422
