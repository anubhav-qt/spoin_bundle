"""ADR-0077: AskAI retrieval, cache, cap, and the off-topic sentinel.

The real streaming call is not exercised (no key in tests); `FakeContentGenerator`
stands in, so these pin the SERVICE's control flow -- cache before cap before
gate, the sentinel watch, the counter -- not prompt quality.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spoin.ask.service import AskService, _utc_day
from spoin.core.config import Settings
from spoin.domain.enums import CardStatus, Difficulty
from spoin.domain.models import AskUsage, Card, CardQa, Subtopic, Topic, User
from spoin.embeddings import HashEmbedder
from spoin.generation.base import CardAnswerQuery
from spoin.generation.fake import FakeContentGenerator


class _OffTopicGenerator(FakeContentGenerator):
    async def stream_card_answer(self, query: CardAnswerQuery) -> AsyncIterator[str]:
        yield "OFF_TOPIC"


async def _card(session: AsyncSession) -> tuple[User, Card]:
    user = User(email=f"{uuid.uuid4()}@t.local", display_name="Ask")
    topic = Topic(slug=f"t-{uuid.uuid4().hex[:8]}", canonical_name="Photosynthesis")
    session.add_all([user, topic])
    await session.flush()
    sub = Subtopic(
        topic_id=topic.id,
        difficulty=Difficulty.BEGINNER,
        title="The light reactions",
        description="How light becomes chemical energy.",
        target_cards=10,
        min_cards=5,
    )
    session.add(sub)
    await session.flush()
    card = Card(
        family_id=uuid.uuid4(),
        topic_id=topic.id,
        subtopic_id=sub.id,
        difficulty=Difficulty.BEGINNER,
        status=CardStatus.ACTIVE,
        title="Chlorophyll absorbs red and blue light",
        canonical_title="Chlorophyll absorbs red and blue light",
        summary="hook",
        body="Chlorophyll reflects green, which is why leaves look green.",
    )
    session.add(card)
    await session.flush()
    return user, card


def _svc(session: AsyncSession, generator: FakeContentGenerator | None = None) -> AskService:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    return AskService(
        session,
        settings,
        generator or FakeContentGenerator(),
        HashEmbedder(settings.embedding_dim),
    )


async def _collect(gen: AsyncIterator[tuple[str, dict[str, object]]]) -> list[str]:
    return [event async for event, _ in gen]


async def test_happy_path_streams_then_done_and_counts(session: AsyncSession) -> None:
    user, card = await _card(session)
    svc = _svc(session)

    events = await _collect(svc.answer(user.id, card.id, "Why are leaves green?"))

    assert events[-1] == "done"
    assert "delta" in events
    qa = await session.scalar(select(CardQa).where(CardQa.card_id == card.id))
    assert qa is not None and qa.on_topic is True
    usage = await session.scalar(select(AskUsage).where(AskUsage.user_id == user.id))
    assert usage is not None and usage.questions_spent == 1


async def test_cache_hit_replays_without_counting(session: AsyncSession) -> None:
    user, card = await _card(session)
    session.add(
        CardQa(
            card_id=card.id,
            question_norm="why are leaves green",
            answer="Because chlorophyll reflects green light.",
            on_topic=True,
        )
    )
    await session.flush()
    svc = _svc(session)

    events = await _collect(svc.answer(user.id, card.id, "Why are leaves GREEN?!"))

    assert events == ["delta", "done"]
    assert await session.scalar(select(AskUsage).where(AskUsage.user_id == user.id)) is None


async def test_daily_cap_emits_limit(session: AsyncSession) -> None:
    user, card = await _card(session)
    svc = _svc(session)
    session.add(
        AskUsage(
            day=_utc_day(datetime.now(UTC)),
            user_id=user.id,
            questions_spent=Settings(_env_file=None).ask_ai_daily_limit,  # type: ignore[call-arg]
        )
    )
    await session.flush()

    events = await _collect(svc.answer(user.id, card.id, "Anything?"))

    assert events == ["limit"]


async def test_off_topic_sentinel_is_not_shown_and_not_counted(session: AsyncSession) -> None:
    user, card = await _card(session)
    svc = _svc(session, _OffTopicGenerator())

    events = await _collect(svc.answer(user.id, card.id, "What is the capital of France?"))

    assert events == ["off_topic"]
    qa = await session.scalar(select(CardQa).where(CardQa.card_id == card.id))
    assert qa is not None and qa.on_topic is False
    assert await session.scalar(select(AskUsage).where(AskUsage.user_id == user.id)) is None


async def test_unknown_card_raises_before_streaming(session: AsyncSession) -> None:
    user, _card_row = await _card(session)
    svc = _svc(session)

    with pytest.raises(HTTPException):
        await _collect(svc.answer(user.id, uuid.uuid4(), "hi"))
