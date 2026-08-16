"""Test fixtures.

The pure logic tests (strata, ranking, interleave) need nothing. The integration
tests need Postgres with pgvector, and **skip rather than fail** when it is absent,
so `pytest` is still useful on a laptop with nothing running.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.sql import text

from slocho.core.config import Settings
from slocho.domain.base import Base
from slocho.domain.enums import CardStatus, Difficulty
from slocho.domain.models import Card, CardStats, Subtopic, Topic, User, UserTopic

TEST_DATABASE_URL = os.environ.get(
    "SLOCHO_TEST_DATABASE_URL",
    os.environ.get("SLOCHO_DATABASE_URL", ""),
)


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    if not TEST_DATABASE_URL:
        pytest.skip("No database configured; set SLOCHO_TEST_DATABASE_URL")

    engine = create_async_engine(TEST_DATABASE_URL)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            # Build the schema from metadata rather than running migrations: tests
            # assert against the models, and a migration bug should fail the
            # migration test, not every test in the suite.
            await connection.run_sync(Base.metadata.drop_all)
            await connection.run_sync(Base.metadata.create_all)
    except Exception as exc:  # pragma: no cover - environment dependent
        await engine.dispose()
        pytest.skip(f"Database unavailable: {exc}")

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        yield db

    await engine.dispose()


@pytest_asyncio.fixture
async def corpus(session: AsyncSession) -> dict[str, object]:
    """A small hand-built corpus: one topic, two subtopics, uneven by difficulty.

    Uneven on purpose — an intermediate pool thinner than the mix asks for is what
    exercises the degraded path, and that is the normal case at launch rather than
    an edge case.
    """

    user = User(email=f"{uuid.uuid4()}@test.local", display_name="Test")
    topic = Topic(slug=f"t-{uuid.uuid4().hex[:8]}", canonical_name="Testing")
    session.add_all([user, topic])
    await session.flush()

    session.add(UserTopic(user_id=user.id, topic_id=topic.id, display_name="Testing"))

    cards: list[Card] = []
    for index, (difficulty, count) in enumerate(
        [(Difficulty.BEGINNER, 12), (Difficulty.INTERMEDIATE, 2)]
    ):
        subtopic = Subtopic(
            topic_id=topic.id,
            difficulty=difficulty,
            title=f"Subtopic {difficulty.value}",
            description="…",
            target_cards=10,
            min_cards=5,
            position=index,
        )
        session.add(subtopic)
        await session.flush()

        for n in range(count):
            card = Card(
                family_id=uuid.uuid4(),
                topic_id=topic.id,
                subtopic_id=subtopic.id,
                difficulty=difficulty,
                status=CardStatus.ACTIVE,
                title=f"{difficulty.value} card {n}",
                summary="hook",
                body="body",
            )
            session.add(card)
            cards.append(card)

    await session.flush()
    session.add_all([CardStats(card_id=card.id) for card in cards])
    await session.flush()

    return {"user": user, "topic": topic, "cards": cards}
