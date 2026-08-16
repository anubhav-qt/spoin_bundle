"""Load the fixture corpus.

`python -m slocho.seed`

The README makes this a first-class requirement rather than a nicety: a new
developer must see a working feed on their first run, without an API key, without
burning quota, and without waiting on generation.

**Idempotent.** Re-running updates in place rather than duplicating, so `make seed`
is safe to run whenever and CI can call it unconditionally.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from importlib import resources
from typing import Any

from sqlalchemy import func, select

from slocho.core.db import session_scope
from slocho.domain.enums import CardStatus, Difficulty, GenerationBackend
from slocho.domain.models import (
    Card,
    CardStats,
    Subtopic,
    Topic,
    TopicAlias,
    User,
    UserTopic,
    UserTopicProgress,
)
from slocho.embeddings import get_embedder, normalize_topic_text


def load_fixture() -> dict[str, Any]:
    source = resources.files("slocho.fixtures").joinpath("corpus.json")
    data: dict[str, Any] = json.loads(source.read_text(encoding="utf-8"))
    return data


async def seed() -> None:
    fixture = load_fixture()
    embedder = get_embedder()

    async with session_scope() as session:
        user = await session.scalar(select(User).where(User.email == fixture["user"]["email"]))
        if user is None:
            user = User(
                email=fixture["user"]["email"],
                display_name=fixture["user"]["display_name"],
            )
            session.add(user)
            await session.flush()

        for topic_data in fixture["topics"]:
            topic = await session.scalar(select(Topic).where(Topic.slug == topic_data["slug"]))
            if topic is None:
                topic = Topic(slug=topic_data["slug"])
                session.add(topic)

            topic.canonical_name = topic_data["canonical_name"]
            topic.description = topic_data["description"]
            topic.is_seeded = True
            topic.embedding = embedder.embed_one(normalize_topic_text(topic_data["canonical_name"]))
            # TEMPORARY (ADR-0015 / docs/tasks/0005): subscriber_count has no live
            # writer other than POST /topics/{id}/subscribe, and with one demo user
            # organic counts would tie every topic at 0-1. Seeding a fixture baseline
            # here makes the Discover box's "popular" ranking demonstrable; delete
            # this line once real subscribe traffic makes it unnecessary.
            topic.subscriber_count = topic_data.get("seed_subscriber_count", 0)
            await session.flush()

            # Aliases are what let a user typing "k8s" land on this topic instead
            # of minting a near-duplicate (ADR-0004). Seeding the obvious ones
            # costs nothing and removes the most common merge decisions entirely.
            for alias in topic_data["aliases"]:
                normalized = normalize_topic_text(alias)
                exists = await session.scalar(
                    select(TopicAlias).where(TopicAlias.normalized_text == normalized)
                )
                if exists is None:
                    session.add(
                        TopicAlias(
                            normalized_text=normalized,
                            raw_text=alias,
                            topic_id=topic.id,
                            decided_by="exact",
                        )
                    )

            # Some fixture topics are deliberately left unsubscribed — a real pool
            # for the Discover surface to draw from. Without this, every seeded
            # topic would be pre-followed and "discover something new" would have
            # nothing to show.
            if topic_data.get("subscribe", True):
                subscription = await session.scalar(
                    select(UserTopic).where(
                        UserTopic.user_id == user.id, UserTopic.topic_id == topic.id
                    )
                )
                if subscription is None:
                    session.add(
                        UserTopic(
                            user_id=user.id,
                            topic_id=topic.id,
                            # The user's own label, which is the whole point of the
                            # shared-entity/personal-label split.
                            display_name=topic_data["display_name"],
                            is_custom=False,
                        )
                    )

                progress = await session.scalar(
                    select(UserTopicProgress).where(
                        UserTopicProgress.user_id == user.id,
                        UserTopicProgress.topic_id == topic.id,
                    )
                )
                if progress is None:
                    session.add(UserTopicProgress(user_id=user.id, topic_id=topic.id))

            for position, subtopic_data in enumerate(topic_data["subtopics"]):
                await _seed_subtopic(session, topic, subtopic_data, position, embedder)

        await session.flush()

    await _report()


async def _seed_subtopic(
    session: Any,
    topic: Topic,
    data: dict[str, Any],
    position: int,
    embedder: Any,
) -> None:
    difficulty = Difficulty(data["difficulty"])

    subtopic = await session.scalar(
        select(Subtopic).where(
            Subtopic.topic_id == topic.id,
            Subtopic.title == data["title"],
            Subtopic.difficulty == difficulty,
        )
    )
    if subtopic is None:
        subtopic = Subtopic(topic_id=topic.id, title=data["title"], difficulty=difficulty)
        session.add(subtopic)

    subtopic.description = data["description"]
    subtopic.target_cards = data["target_cards"]
    subtopic.min_cards = data["min_cards"]
    subtopic.position = position
    await session.flush()

    for card_data in data["cards"]:
        card = await session.scalar(
            select(Card).where(Card.subtopic_id == subtopic.id, Card.title == card_data["title"])
        )
        if card is None:
            card = Card(
                family_id=uuid.uuid4(),
                version=1,
                topic_id=topic.id,
                subtopic_id=subtopic.id,
                difficulty=difficulty,
            )
            session.add(card)

        card.title = card_data["title"]
        card.summary = card_data["summary"]
        card.body = card_data["body"]
        # Fixture cards bypass the quality gate and land ACTIVE directly. They are
        # hand-written and reviewed in the diff, which is a stronger guarantee than
        # the gate provides. `gen_meta.backend` records that, so a later quality
        # comparison across backends is not silently polluted by fixtures.
        card.status = CardStatus.ACTIVE
        card.gen_meta = {
            "backend": GenerationBackend.FIXTURE.value,
            "prompt_version": None,
            "batch_id": "seed",
        }
        card.content_embedding = embedder.embed_one(f"{card_data['title']} {card_data['body']}")
        await session.flush()

        stats = await session.scalar(select(CardStats).where(CardStats.card_id == card.id))
        if stats is None:
            # A stats row from the start, so the feed's join never has to cope with
            # a missing one and `quality` starts at a neutral zero rather than NULL.
            session.add(CardStats(card_id=card.id))


async def _report() -> None:
    async with session_scope() as session:
        topics = await session.scalar(select(func.count()).select_from(Topic))
        subtopics = await session.scalar(select(func.count()).select_from(Subtopic))
        cards = await session.scalar(select(func.count()).select_from(Card))
        print(f"seeded: {topics} topics, {subtopics} subtopics, {cards} cards")


def main() -> None:
    asyncio.run(seed())


if __name__ == "__main__":
    main()
