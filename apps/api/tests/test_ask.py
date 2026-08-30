"""ADR-0077 (revised): AskAI as a persistent, topic-scoped conversation.

The real streaming call is not exercised (no key in tests); `FakeContentGenerator`
stands in, so these pin the SERVICE's control flow -- cap before turn, history
carried, the sentinel watch, the counter, reset -- not prompt quality.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import ClassVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spoin.ask.service import AskService, _utc_day
from spoin.core.config import Settings
from spoin.domain.enums import CardStatus, Difficulty
from spoin.domain.models import (
    AskConversation,
    AskMessage,
    AskUsage,
    Card,
    Subtopic,
    Topic,
    User,
)
from spoin.embeddings import HashEmbedder
from spoin.generation.base import AskTurnQuery
from spoin.generation.fake import FakeContentGenerator


class _OffTopicGenerator(FakeContentGenerator):
    async def stream_topic_answer(self, query: AskTurnQuery) -> AsyncIterator[str]:
        yield "OFF_TOPIC"


async def _topic(session: AsyncSession) -> tuple[User, Topic, Card]:
    user = User(email=f"{uuid.uuid4()}@t.local", display_name="Ask")
    topic = Topic(
        slug=f"t-{uuid.uuid4().hex[:8]}",
        canonical_name="Photosynthesis",
        description="How plants turn light into sugar.",
    )
    session.add_all([user, topic])
    await session.flush()
    sub = Subtopic(
        topic_id=topic.id,
        difficulty=Difficulty.BEGINNER,
        title="The light reactions",
        description="Light to chemical energy.",
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
        title="Chlorophyll reflects green",
        canonical_title="Chlorophyll reflects green",
        summary="hook",
        body="Chlorophyll absorbs red and blue and reflects green.",
    )
    session.add(card)
    await session.flush()
    return user, topic, card


def _svc(session: AsyncSession, generator: FakeContentGenerator | None = None) -> AskService:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    return AskService(
        session, settings, generator or FakeContentGenerator(), HashEmbedder(settings.embedding_dim)
    )


async def _events(gen: AsyncIterator[tuple[str, dict[str, object]]]) -> list[str]:
    return [e async for e, _ in gen]


async def test_turn_streams_appends_both_messages_and_counts(session: AsyncSession) -> None:
    user, topic, card = await _topic(session)
    svc = _svc(session)

    events = await _events(svc.answer(user.id, topic.id, "Why do leaves look green?", card.id))

    assert events[-1] == "done"
    assert "delta" in events
    convo = await session.scalar(select(AskConversation).where(AskConversation.user_id == user.id))
    assert convo is not None and convo.status == "active"
    msgs = (
        (
            await session.execute(
                select(AskMessage)
                .where(AskMessage.conversation_id == convo.id)
                .order_by(AskMessage.created_at)
            )
        )
        .scalars()
        .all()
    )
    assert [m.role for m in msgs] == ["user", "assistant"]
    usage = await session.scalar(select(AskUsage).where(AskUsage.user_id == user.id))
    assert usage is not None and usage.questions_spent == 1


async def test_second_turn_carries_history_and_reuses_the_conversation(
    session: AsyncSession,
) -> None:
    user, topic, _card = await _topic(session)

    class _Recorder(FakeContentGenerator):
        seen_history: ClassVar[list[tuple[str, str]]] = []

        async def stream_topic_answer(self, query: AskTurnQuery) -> AsyncIterator[str]:
            _Recorder.seen_history = list(query.history)
            yield "second answer."

    svc = _svc(session)
    await _events(svc.answer(user.id, topic.id, "First question?", None))
    svc2 = _svc(session, _Recorder())
    await _events(svc2.answer(user.id, topic.id, "And why is that?", None))

    assert [r for r, _ in _Recorder.seen_history] == ["user", "assistant"]
    convos = (
        (await session.execute(select(AskConversation).where(AskConversation.user_id == user.id)))
        .scalars()
        .all()
    )
    assert len(convos) == 1


async def test_reset_archives_and_a_new_turn_opens_a_fresh_thread(session: AsyncSession) -> None:
    user, topic, _card = await _topic(session)
    svc = _svc(session)
    await _events(svc.answer(user.id, topic.id, "Q1?", None))

    await svc.reset(user.id, topic.id)
    await _events(svc.answer(user.id, topic.id, "Q2?", None))

    rows = (
        (
            await session.execute(
                select(AskConversation)
                .where(AskConversation.user_id == user.id)
                .order_by(AskConversation.created_at)
            )
        )
        .scalars()
        .all()
    )
    assert [c.status for c in rows] == ["archived", "active"]


async def test_daily_cap_emits_limit_and_writes_nothing(session: AsyncSession) -> None:
    user, topic, _card = await _topic(session)
    svc = _svc(session)
    session.add(
        AskUsage(
            day=_utc_day(datetime.now(UTC)),
            user_id=user.id,
            questions_spent=Settings(_env_file=None).ask_ai_daily_limit,  # type: ignore[call-arg]
        )
    )
    await session.flush()

    events = await _events(svc.answer(user.id, topic.id, "Anything?", None))

    assert events == ["limit"]
    assert (
        await session.scalar(select(AskConversation).where(AskConversation.user_id == user.id))
        is None
    )


async def test_off_topic_sentinel_is_refused_and_not_counted(session: AsyncSession) -> None:
    user, topic, _card = await _topic(session)
    svc = _svc(session, _OffTopicGenerator())

    events = await _events(svc.answer(user.id, topic.id, "Capital of France?", None))

    assert events == ["off_topic"]
    convo = await session.scalar(select(AskConversation).where(AskConversation.user_id == user.id))
    assert convo is not None
    msgs = (
        (await session.execute(select(AskMessage).where(AskMessage.conversation_id == convo.id)))
        .scalars()
        .all()
    )
    assert {m.role: m.on_topic for m in msgs} == {"user": True, "assistant": False}
    assert await session.scalar(select(AskUsage).where(AskUsage.user_id == user.id)) is None


async def test_get_conversation_returns_messages_and_budget(session: AsyncSession) -> None:
    user, topic, _card = await _topic(session)
    svc = _svc(session)
    await _events(svc.answer(user.id, topic.id, "Q?", None))

    out = await svc.get_conversation(user.id, topic.id)

    assert out.conversation_id is not None
    assert [m.role for m in out.messages] == ["user", "assistant"]
    assert out.spent == 1
    assert out.limit == Settings(_env_file=None).ask_ai_daily_limit  # type: ignore[call-arg]
