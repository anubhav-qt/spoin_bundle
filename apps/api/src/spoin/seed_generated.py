"""Load `fixtures/generated_corpus.json` — the Opus/Sonnet generation experiment.

`python -m spoin.seed_generated`

Mirrors seed.py's insertion pattern exactly (same embedder, same archetype
derivation, same CardStats bootstrap), with one deliberate difference: cards
here get `gen_meta.backend = "opus_sonnet_experiment"`, never `"fixture"`.
corpus.json is hand-written and reviewed in the diff; this content is
LLM-planned and LLM-written, unreviewed line-by-line by a human. Collapsing
that distinction would corrupt the provenance tracking gen_meta exists for
(ADR-0011) — a real generation backend eventually needs to be told apart from
both hand-written fixtures and each other.

Run after seed.py (topics here assume the demo user already exists). Also
idempotent, same as seed.py: safe to re-run.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from importlib import resources
from typing import Any

from frog.embeddings import normalize_topic_text
from sqlalchemy import select

from spoin.content.archetype import classify_archetype
from spoin.core.db import session_scope
from spoin.domain.enums import CardStatus, Difficulty
from spoin.domain.models import (
    Card,
    CardStats,
    Subtopic,
    Topic,
    User,
    UserTopic,
    UserTopicProgress,
)
from spoin.embeddings import get_embedder


def load_generated_fixture() -> dict[str, Any]:
    source = resources.files("spoin.fixtures").joinpath("generated_corpus.json")
    data: dict[str, Any] = json.loads(source.read_text(encoding="utf-8"))
    return data


async def seed_generated() -> None:
    fixture = load_generated_fixture()
    embedder = get_embedder()

    async with session_scope() as session:
        # Same demo user seed.py creates — this script assumes seed.py already ran.
        user = await session.scalar(select(User).where(User.email == "dev@spoin.local"))
        if user is None:
            raise RuntimeError("demo user not found — run `python -m spoin.seed` first")

        for topic_data in fixture["topics"]:
            topic = await session.scalar(select(Topic).where(Topic.slug == topic_data["slug"]))
            if topic is None:
                topic = Topic(slug=topic_data["slug"])
                session.add(topic)

            topic.canonical_name = topic_data["canonical_name"]
            topic.description = topic_data["description"]
            topic.is_seeded = True
            topic.is_survey = topic_data.get("is_survey", False)
            topic.embedding = embedder.embed_one_passage(
                normalize_topic_text(topic_data["canonical_name"])
            )
            await session.flush()

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
                        display_name=topic_data["display_name"],
                        is_custom=False,
                    )
                )

            progress = await session.scalar(
                select(UserTopicProgress).where(
                    UserTopicProgress.user_id == user.id, UserTopicProgress.topic_id == topic.id
                )
            )
            if progress is None:
                session.add(UserTopicProgress(user_id=user.id, topic_id=topic.id))

            for position, subtopic_data in enumerate(topic_data["subtopics"]):
                await _seed_subtopic(session, topic, subtopic_data, position, embedder)

        await session.flush()

    print("seeded generated_corpus.json")


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
        card.canonical_title = card_data.get("canonical_title", card_data["title"])
        card.summary = card_data["summary"]
        card.body = card_data["body"]
        card.archetype = classify_archetype(card.body)
        card.is_hero = card_data["is_hero"]
        card.status = CardStatus.ACTIVE
        # The one deliberate divergence from seed.py — see module docstring.
        card.gen_meta = {
            "backend": "opus_sonnet_experiment",
            "prompt_version": None,
            "batch_id": topic.slug,
        }
        card.content_embedding = embedder.embed_one_passage(
            f"{card_data['title']} {card_data['body']}"
        )
        await session.flush()

        stats = await session.scalar(select(CardStats).where(CardStats.card_id == card.id))
        if stats is None:
            session.add(CardStats(card_id=card.id))


def main() -> None:
    asyncio.run(seed_generated())


if __name__ == "__main__":
    main()
