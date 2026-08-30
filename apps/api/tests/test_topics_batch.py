"""POST /topics/batch — several custom topics in one submission (task 0032).

Same real-`session` rationale as `test_topics_request.py`: topic matching needs
real pgvector distance queries. `get_content_generator`/`get_embedder` default to
the fake/hash backends, so nothing here touches the network. The fake's
`validate_topic_names` rejects any name containing "trolltest".
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from spoin.api.routers.topics import request_topics_batch
from spoin.api.schemas import TopicBatchIn, TopicRequestIn
from spoin.domain.models import GenerationJob, User, UserTopic


async def _make_user(session: AsyncSession, *, guest: bool = False) -> uuid.UUID:
    user = User(
        email=None if guest else f"{uuid.uuid4()}@test.local",
        display_name="Guest" if guest else "Test",
    )
    session.add(user)
    await session.flush()
    return user.id


def _batch(*names: str) -> TopicBatchIn:
    return TopicBatchIn(items=[TopicRequestIn(name=n) for n in names])


async def test_batch_mints_every_distinct_new_topic(session: AsyncSession) -> None:
    user_id = await _make_user(session)

    out = await request_topics_batch(_batch("Photosynthesis", "Plate Tectonics"), session, user_id)

    assert [r.status for r in out.results] == ["generating", "generating"]
    assert [r.request_index for r in out.results] == [0, 1]
    assert {r.topic.display_name for r in out.results if r.topic} == {
        "Photosynthesis",
        "Plate Tectonics",
    }

    subs = (
        (await session.execute(select(UserTopic).where(UserTopic.user_id == user_id)))
        .scalars()
        .all()
    )
    assert len(subs) == 2
    job_count = await session.scalar(
        select(func.count())
        .select_from(GenerationJob)
        .where(GenerationJob.topic_id.in_([s.topic_id for s in subs]))
    )
    assert job_count == 2


async def test_batch_reports_each_row_independently(session: AsyncSession) -> None:
    user_id = await _make_user(session)

    # Row 1's name trips the fake validator; the other two are fine.
    out = await request_topics_batch(
        _batch("Cell Biology", "trolltest nonsense", "Roman History"), session, user_id
    )

    assert [r.status for r in out.results] == ["generating", "rejected", "generating"]
    assert out.results[1].detail == "simulated rejection"
    assert out.results[1].topic is None
    # The rejected row minted nothing.
    subs = await session.scalar(
        select(func.count()).select_from(UserTopic).where(UserTopic.user_id == user_id)
    )
    assert subs == 2


async def test_batch_row_for_an_already_followed_topic(session: AsyncSession) -> None:
    user_id = await _make_user(session)

    first = await request_topics_batch(_batch("Entropy"), session, user_id)
    assert first.results[0].status == "generating"
    entropy = first.results[0].topic
    assert entropy is not None

    out = await request_topics_batch(_batch("Entropy", "Graph Theory"), session, user_id)

    assert [r.status for r in out.results] == ["already_subscribed", "generating"]
    assert out.results[0].topic is None
    # Still just one subscription to the first topic — no duplicate row, no
    # second job.
    entropy_subs = await session.scalar(
        select(func.count())
        .select_from(UserTopic)
        .where(UserTopic.user_id == user_id, UserTopic.topic_id == entropy.id)
    )
    assert entropy_subs == 1


async def test_batch_word_count_rejected_in_code(session: AsyncSession) -> None:
    user_id = await _make_user(session)

    out = await request_topics_batch(
        _batch("this topic name has far too many words in it"), session, user_id
    )

    assert out.results[0].status == "rejected"
    assert "words or fewer" in (out.results[0].detail or "")


async def test_batch_over_the_cap_is_422(session: AsyncSession) -> None:
    user_id = await _make_user(session)

    payload = TopicBatchIn(items=[TopicRequestIn(name=f"Topic {i}") for i in range(6)])
    with pytest.raises(HTTPException) as exc_info:
        await request_topics_batch(payload, session, user_id)
    assert exc_info.value.status_code == 422


async def test_batch_rejected_for_a_guest(session: AsyncSession) -> None:
    guest_id = await _make_user(session, guest=True)

    with pytest.raises(HTTPException) as exc_info:
        await request_topics_batch(_batch("Astronomy"), session, guest_id)
    assert exc_info.value.status_code == 403


async def test_batch_of_one_behaves_like_the_single_endpoint(session: AsyncSession) -> None:
    user_id = await _make_user(session)

    out = await request_topics_batch(_batch("Number Theory"), session, user_id)

    assert len(out.results) == 1
    assert out.results[0].status == "generating"
    assert out.results[0].topic is not None
    assert out.results[0].topic.is_custom is True
