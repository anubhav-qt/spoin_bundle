"""ADR-0077: the AskAI retrieval + streaming service.

`AskService.answer` is an async generator of `(event, payload)` pairs; the router
serialises them as SSE. Events: `delta` (answer chunk), `done`, `off_topic`
(with a `hint`), `limit` (daily cap), `error` (with an ADR-0065 `cause`).
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from spoin.core.config import Settings
from spoin.domain.enums import CardStatus
from spoin.domain.models import AskUsage, Card, CardQa, Subtopic, Topic
from spoin.embeddings import Embedder, HashEmbedder
from spoin.generation.base import CardAnswerQuery, ContentGenerator
from spoin.generation.quota import QuotaExhaustedError

_OFF_TOPIC = "OFF_TOPIC"
_SENTINEL_WINDOW = 24  # chars to buffer before deciding it is / isn't the sentinel
_WS = re.compile(r"[^a-z0-9]+")

_Event = tuple[str, dict[str, object]]


def normalize_question(raw: str) -> str:
    """Lowercase, collapse non-alphanumerics to single spaces -- the `card_qa`
    cache key. Same spirit as `normalize_topic_text`."""

    return _WS.sub(" ", raw.strip().lower()).strip()[:500]


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

    async def answer(
        self, user_id: UUID, card_id: UUID, question: str
    ) -> AsyncIterator[_Event]:
        card = await self._session.get(Card, card_id)
        if card is None or card.status != CardStatus.ACTIVE:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No such card")

        qnorm = normalize_question(question)
        if not qnorm:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Empty question")

        # 1. Cache -- costs nothing, counts nothing.
        cached = await self._session.scalar(
            select(CardQa).where(CardQa.card_id == card_id, CardQa.question_norm == qnorm)
        )
        if cached is not None:
            if cached.on_topic:
                yield ("delta", {"text": cached.answer})
                yield ("done", {})
            else:
                yield ("off_topic", {"hint": cached.answer or self._hint(card)})
            return

        # 2. Daily cap.
        now = datetime.now(UTC)
        usage = await self._session.get(AskUsage, (_utc_day(now), user_id))
        if usage is not None and usage.questions_spent >= self._settings.ask_ai_daily_limit:
            yield ("limit", {})
            return

        topic = await self._session.get(Topic, card.topic_id)
        subtopic = await self._session.get(Subtopic, card.subtopic_id)
        assert topic is not None and subtopic is not None

        # 3. Free embedding pre-check (skipped under the hash stand-in).
        if not isinstance(self._embedder, HashEmbedder):
            qvec = (await self._embedder.aembed([question]))[0]
            refs = [
                v
                for v in (card.content_embedding, topic.embedding)
                if v is not None
            ]
            best = max((_cosine(qvec, list(v)) for v in refs), default=1.0)
            if best < self._settings.ask_ai_topic_similarity_floor:
                await self._remember(card_id, qnorm, on_topic=False, answer=self._hint(card))
                yield ("off_topic", {"hint": self._hint(card)})
                return

        context = await self._assemble_context(card, topic, subtopic)
        query = CardAnswerQuery(
            card_title=card.canonical_title,
            topic_name=topic.canonical_name,
            context=context,
            question=question,
        )

        # 4. One streamed call. Watch the opening for the OFF_TOPIC sentinel.
        buffer = ""
        decided = False
        answer_parts: list[str] = []
        try:
            async for chunk in self._generator.stream_card_answer(query):
                if decided:
                    answer_parts.append(chunk)
                    yield ("delta", {"text": chunk})
                    continue
                buffer += chunk
                stripped = buffer.lstrip()
                if _OFF_TOPIC.startswith(stripped[: len(_OFF_TOPIC)]) and len(stripped) < len(
                    _OFF_TOPIC
                ):
                    continue  # still ambiguous, keep buffering
                if stripped[: len(_OFF_TOPIC)] == _OFF_TOPIC and (
                    len(stripped) <= _SENTINEL_WINDOW
                ):
                    await self._remember(card_id, qnorm, on_topic=False, answer=self._hint(card))
                    yield ("off_topic", {"hint": self._hint(card)})
                    return
                decided = True
                answer_parts.append(buffer)
                yield ("delta", {"text": buffer})
        except QuotaExhaustedError as exc:
            yield ("error", {"cause": type(exc).__name__})
            return
        except Exception as exc:
            yield ("error", {"cause": f"stream failed: {exc}"})
            return

        answer = "".join(answer_parts).strip()
        if not answer:
            yield ("error", {"cause": "empty answer"})
            return
        await self._remember(card_id, qnorm, on_topic=True, answer=answer)
        await self._bump_usage(user_id, now)
        yield ("done", {})

    # -- internals ------------------------------------------------------

    def _hint(self, card: Card) -> str:
        return f"That's outside this card. It covers: {card.canonical_title}."

    async def _remember(
        self, card_id: UUID, qnorm: str, *, on_topic: bool, answer: str
    ) -> None:
        self._session.add(
            CardQa(card_id=card_id, question_norm=qnorm, answer=answer, on_topic=on_topic)
        )
        await self._session.commit()

    async def _bump_usage(self, user_id: UUID, now: datetime) -> None:
        day = _utc_day(now)
        usage = await self._session.get(AskUsage, (day, user_id))
        if usage is None:
            self._session.add(AskUsage(day=day, user_id=user_id, questions_spent=1))
        else:
            usage.questions_spent += 1
        await self._session.commit()

    async def _assemble_context(self, card: Card, topic: Topic, subtopic: Subtopic) -> str:
        siblings = (
            (
                await self._session.execute(
                    select(Subtopic.title)
                    .where(Subtopic.topic_id == topic.id, Subtopic.id != subtopic.id)
                    .order_by(Subtopic.position)
                    .limit(12)
                )
            )
            .scalars()
            .all()
        )
        adjacent = (
            (
                await self._session.execute(
                    select(Subtopic.title, Subtopic.difficulty).where(
                        Subtopic.subtopic_group_id == subtopic.subtopic_group_id,
                        Subtopic.id != subtopic.id,
                    )
                )
            )
            .all()
        )

        neighbours: list[tuple[str, str]] = []
        if card.content_embedding is not None:
            rows = (
                await self._session.execute(
                    select(Card.canonical_title, Card.body)
                    .where(
                        Card.topic_id == topic.id,
                        Card.status == CardStatus.ACTIVE,
                        Card.id != card.id,
                    )
                    .order_by(Card.content_embedding.cosine_distance(card.content_embedding))
                    .limit(self._settings.ask_ai_context_neighbours)
                )
            ).all()
            neighbours = [(t, b) for t, b in rows]

        parts = [
            f"TOPIC: {topic.canonical_name}",
            f"  {topic.description or ''}".rstrip(),
            f"SUBTOPIC: {subtopic.title}",
            f"  {subtopic.description}",
            "",
            f"THIS CARD: {card.canonical_title}",
            card.body,
        ]
        if card.visual_slots and card.visual_slots.get("alt"):
            parts.append(f"(the card also shows a diagram: {card.visual_slots['alt']})")
        if adjacent:
            parts.append("")
            parts.append("SAME CONCEPT AT OTHER LEVELS:")
            parts += [f"  - {t} ({d})" for t, d in adjacent]
        if siblings:
            parts.append("")
            parts.append("OTHER SUBTOPICS IN THIS TOPIC:")
            parts += [f"  - {t}" for t in siblings]
        if neighbours:
            parts.append("")
            parts.append("RELATED CARDS:")
            for t, b in neighbours:
                parts.append(f"  - {t}: {b[:280].strip()}")
        return "\n".join(parts)


async def question_count_today(session: AsyncSession, user_id: UUID) -> int:
    """Read-only helper for the client to show remaining budget."""

    day = _utc_day(datetime.now(UTC))
    return (
        await session.scalar(
            select(func.coalesce(AskUsage.questions_spent, 0)).where(
                AskUsage.day == day, AskUsage.user_id == user_id
            )
        )
    ) or 0
