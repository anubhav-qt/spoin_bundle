"""ADR-0077 (revised): the AskAI conversation service.

Topic-scoped, persistent. `AskService.answer` is an async generator of
`(event, payload)` pairs the router serialises as SSE. Events: `delta`
(assistant chunk), `done`, `off_topic` (with a `hint`), `limit` (daily cap),
`error` (with an ADR-0065 `cause`).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from frog.embeddings import Embedder, HashEmbedder
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from spoin.api.schemas import AskConversationOut, AskMessageOut
from spoin.core.config import Settings
from spoin.domain.enums import CardStatus
from spoin.domain.models import (
    AskConversation,
    AskMessage,
    AskUsage,
    Card,
    Subtopic,
    Topic,
)
from spoin.generation.base import AskTurnQuery, ContentGenerator
from spoin.generation.quota import QuotaExhaustedError

_OFF_TOPIC = "OFF_TOPIC"
_SENTINEL_WINDOW = 24
#: A follow-up in an already-on-topic thread gets the floor relaxed by this
#: factor -- "why?" is on-topic in context, off-topic in isolation.
_FOLLOWUP_FLOOR_FACTOR = 0.5

_Event = tuple[str, dict[str, object]]


def _utc_day(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


class AskService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        generator: ContentGenerator,
        embedder: Embedder,
    ) -> None:
        self._session = session
        self._settings = settings
        self._generator = generator
        self._embedder = embedder

    # -- reads ----------------------------------------------------------

    async def get_conversation(self, user_id: UUID, topic_id: UUID) -> AskConversationOut:
        convo = await self._active_conversation(user_id, topic_id)
        messages: list[AskMessageOut] = []
        if convo is not None:
            rows = (
                (
                    await self._session.execute(
                        select(AskMessage)
                        .where(AskMessage.conversation_id == convo.id)
                        .order_by(AskMessage.created_at)
                    )
                )
                .scalars()
                .all()
            )
            messages = [
                AskMessageOut(
                    role=m.role, content=m.content, on_topic=m.on_topic, created_at=m.created_at
                )
                for m in rows
            ]
        return AskConversationOut(
            conversation_id=convo.id if convo else None,
            messages=messages,
            spent=await self._spent_today(user_id),
            limit=self._settings.ask_ai_daily_limit,
        )

    async def reset(self, user_id: UUID, topic_id: UUID) -> None:
        convo = await self._active_conversation(user_id, topic_id)
        if convo is not None:
            convo.status = "archived"
            await self._session.commit()

    # -- the turn -----------------------------------------------------

    async def answer(
        self, user_id: UUID, topic_id: UUID, question: str, card_id: UUID | None
    ) -> AsyncIterator[_Event]:
        topic = await self._session.get(Topic, topic_id)
        if topic is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No such topic")

        now = datetime.now(UTC)
        if await self._spent_today(user_id) >= self._settings.ask_ai_daily_limit:
            yield ("limit", {})
            return

        convo = await self._get_or_create_conversation(user_id, topic_id)
        history = await self._history(convo.id)

        subtopics = await self._subtopics(topic_id)
        current_card = await self._session.get(Card, card_id) if card_id else None
        neighbours = await self._nearest_cards(topic_id, question)

        # Embedding pre-check (skipped under the hash stand-in).
        if not isinstance(self._embedder, HashEmbedder):
            qvec = (await self._embedder.aembed([question]))[0]
            refs = [topic.embedding, *(c.content_embedding for c in neighbours)]
            best = max((_cosine(qvec, list(v)) for v in refs if v is not None), default=1.0)
            floor = self._settings.ask_ai_topic_similarity_floor
            if history and history[-1][0] == "assistant":
                floor *= _FOLLOWUP_FLOOR_FACTOR
            if best < floor:
                hint = self._hint(topic)
                await self._append(convo, "user", question, on_topic=True)
                await self._append(convo, "assistant", hint, on_topic=False, commit=True)
                yield ("off_topic", {"hint": hint})
                return

        context = self._assemble_context(topic, subtopics, neighbours, current_card)
        query = AskTurnQuery(
            topic_name=topic.canonical_name,
            subtopics=[s.title for s in subtopics],
            current_card_title=current_card.canonical_title if current_card else None,
            context=context,
            history=history,
            question=question,
        )

        # Persist the user turn now, so it survives a stream that dies mid-answer.
        await self._append(convo, "user", question, on_topic=True, commit=True)

        buffer = ""
        decided = False
        parts: list[str] = []
        try:
            async for chunk in self._generator.stream_topic_answer(query):
                if decided:
                    parts.append(chunk)
                    yield ("delta", {"text": chunk})
                    continue
                buffer += chunk
                stripped = buffer.lstrip()
                if _OFF_TOPIC.startswith(stripped[: len(_OFF_TOPIC)]) and len(stripped) < len(
                    _OFF_TOPIC
                ):
                    continue
                if stripped[: len(_OFF_TOPIC)] == _OFF_TOPIC and len(stripped) <= _SENTINEL_WINDOW:
                    hint = self._hint(topic)
                    await self._append(convo, "assistant", hint, on_topic=False, commit=True)
                    yield ("off_topic", {"hint": hint})
                    return
                decided = True
                parts.append(buffer)
                yield ("delta", {"text": buffer})
        except QuotaExhaustedError as exc:
            yield ("error", {"cause": type(exc).__name__})
            return
        except Exception as exc:
            yield ("error", {"cause": f"stream failed: {exc}"})
            return

        answer = "".join(parts).strip()
        if not answer:
            yield ("error", {"cause": "empty answer"})
            return
        await self._append(convo, "assistant", answer, on_topic=True)
        convo.last_message_at = now
        await self._bump_usage(user_id, now)
        await self._session.commit()
        yield ("done", {})

    # -- internals --------------------------------------------------

    def _hint(self, topic: Topic) -> str:
        return f"That's outside this topic. It covers: {topic.canonical_name}."

    async def _active_conversation(self, user_id: UUID, topic_id: UUID) -> AskConversation | None:
        convo: AskConversation | None = await self._session.scalar(
            select(AskConversation).where(
                AskConversation.user_id == user_id,
                AskConversation.topic_id == topic_id,
                AskConversation.status == "active",
            )
        )
        return convo

    async def _get_or_create_conversation(self, user_id: UUID, topic_id: UUID) -> AskConversation:
        convo = await self._active_conversation(user_id, topic_id)
        if convo is not None:
            return convo
        convo = AskConversation(user_id=user_id, topic_id=topic_id, status="active")
        self._session.add(convo)
        try:
            await self._session.flush()
        except IntegrityError:  # a concurrent first turn won the partial-unique index
            await self._session.rollback()
            existing = await self._active_conversation(user_id, topic_id)
            assert existing is not None
            return existing
        return convo

    async def _history(self, conversation_id: UUID) -> list[tuple[str, str]]:
        rows = (
            await self._session.execute(
                select(AskMessage.role, AskMessage.content, AskMessage.on_topic)
                .where(AskMessage.conversation_id == conversation_id)
                .order_by(AskMessage.created_at)
            )
        ).all()
        # Drop refused assistant turns from what the model sees -- the hint is
        # UI copy, not part of the dialogue.
        return [(role, content) for role, content, on_topic in rows if on_topic]

    async def _append(
        self,
        convo: AskConversation,
        role: str,
        content: str,
        *,
        on_topic: bool,
        commit: bool = False,
    ) -> None:
        self._session.add(
            AskMessage(conversation_id=convo.id, role=role, content=content, on_topic=on_topic)
        )
        if commit:
            await self._session.commit()
        else:
            await self._session.flush()

    async def _spent_today(self, user_id: UUID) -> int:
        return (
            await self._session.scalar(
                select(func.coalesce(AskUsage.questions_spent, 0)).where(
                    AskUsage.day == _utc_day(datetime.now(UTC)), AskUsage.user_id == user_id
                )
            )
        ) or 0

    async def _bump_usage(self, user_id: UUID, now: datetime) -> None:
        day = _utc_day(now)
        usage = await self._session.get(AskUsage, (day, user_id))
        if usage is None:
            self._session.add(AskUsage(day=day, user_id=user_id, questions_spent=1))
        else:
            usage.questions_spent += 1

    async def _subtopics(self, topic_id: UUID) -> list[Subtopic]:
        return list(
            (
                await self._session.execute(
                    select(Subtopic)
                    .where(Subtopic.topic_id == topic_id)
                    .order_by(Subtopic.position)
                )
            )
            .scalars()
            .all()
        )

    async def _nearest_cards(self, topic_id: UUID, question: str) -> list[Card]:
        if isinstance(self._embedder, HashEmbedder):
            stmt = (
                select(Card)
                .where(Card.topic_id == topic_id, Card.status == CardStatus.ACTIVE)
                .order_by(Card.created_at.desc())
                .limit(self._settings.ask_ai_context_neighbours)
            )
        else:
            qvec = (await self._embedder.aembed([question]))[0]
            stmt = (
                select(Card)
                .where(
                    Card.topic_id == topic_id,
                    Card.status == CardStatus.ACTIVE,
                    Card.content_embedding.is_not(None),
                )
                .order_by(Card.content_embedding.cosine_distance(qvec))
                .limit(self._settings.ask_ai_context_neighbours)
            )
        return list((await self._session.execute(stmt)).scalars().all())

    def _assemble_context(
        self,
        topic: Topic,
        subtopics: list[Subtopic],
        neighbours: list[Card],
        current_card: Card | None,
    ) -> str:
        parts = [f"TOPIC: {topic.canonical_name}", f"  {topic.description or ''}".rstrip(), ""]
        parts.append("SUBTOPICS:")
        parts += [f"  - {s.title}: {s.description}" for s in subtopics]
        if current_card is not None:
            parts += [
                "",
                f"THE CARD THE LEARNER IS ON: {current_card.canonical_title}",
                current_card.body,
            ]
        if neighbours:
            parts += ["", "RELEVANT CARDS FROM THIS TOPIC:"]
            for c in neighbours:
                parts.append(f"  ## {c.canonical_title}")
                parts.append(f"  {c.body[:600].strip()}")
        return "\n".join(parts)
