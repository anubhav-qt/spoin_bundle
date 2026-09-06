"""Test fixtures.

The pure logic tests (strata, ranking, interleave) need nothing. The integration
tests need Postgres with pgvector, and **skip rather than fail** when it is absent,
so `pytest` is still useful on a laptop with nothing running.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from frog.universe.base import Base as UniverseBase
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.sql import text

from spoin.core.config import Settings
from spoin.domain.base import Base
from spoin.domain.enums import CardStatus, Difficulty
from spoin.domain.models import Card, CardStats, Subtopic, Topic, User, UserTopic

# Deliberately NOT falling back to SPOIN_DATABASE_URL: that fallback is what
# let this fixture silently target a real dev database when only
# SPOIN_DATABASE_URL happened to be set in the environment. SPOIN_TEST_DATABASE_URL
# must be set explicitly, every time -- `make test` / `docker compose --profile
# test run --rm test` (see docker-compose.yml's `test` service) sets it for you,
# pointed at the dedicated `spoin_test` database.
TEST_DATABASE_URL = os.environ.get("SPOIN_TEST_DATABASE_URL", "")


def _reject_unsafe_test_database(url: str, variable: str = "SPOIN_TEST_DATABASE_URL") -> None:
    """Hard-stop, not a skip: this fixture is about to DROP AND RECREATE every
    table on `url` below. A skip is silent and easy to miss; a real database
    getting wiped because of it is not something to fail quietly on. Requires
    the database name to end in `_test` -- `spoin_test`, never `spoin` (the
    dev/prod name) -- as a second line of defense on top of "use `make test`",
    for whoever (human or agent) runs pytest directly with a hand-built URL
    instead."""

    db_name = url.rsplit("/", 1)[-1].split("?", 1)[0]
    if not db_name.endswith("_test"):
        raise RuntimeError(
            f"{variable} points at database {db_name!r}, which does not "
            "end in `_test`. This fixture drops and recreates every table it touches "
            "-- refusing to run against what looks like a real database. Use `make "
            "test` (or `docker compose --profile test run --rm test`), which points "
            "at the dedicated `spoin_test` database instead."
        )


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    if not TEST_DATABASE_URL:
        pytest.skip("No database configured; set SPOIN_TEST_DATABASE_URL")
    _reject_unsafe_test_database(TEST_DATABASE_URL)

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


#: The corpus database (ADR-0088), for `test_grounding.py`. Its own variable and never
#: SPOIN_UNIVERSE_DATABASE_URL, for the same reason as above: the fixture below drops
#: and recreates every table it points at, and `the_spoin_universe` is a real corpus
#: someone may be mid-ingestion into.
UNIVERSE_TEST_DATABASE_URL = os.environ.get("SPOIN_UNIVERSE_TEST_DATABASE_URL", "")


@pytest_asyncio.fixture
async def universe_sessions() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A sessionmaker on an empty corpus database.

    Grounding is `spoin`'s (ADR-0087 puts packing on this side of the boundary), so its
    tests live here rather than in frog's suite — but what they exercise is frog's
    schema, so the fixture builds frog's metadata.

    A maker rather than a session, because the pipeline retrieves from concurrent
    subtopic branches and `AsyncSession` is not safe for concurrent use. Production
    takes one session per retrieval from a pool; a test sharing one across branches
    would fail on that instead of on what it is testing.
    """

    if not UNIVERSE_TEST_DATABASE_URL:
        pytest.skip("No corpus database configured; set SPOIN_UNIVERSE_TEST_DATABASE_URL")
    _reject_unsafe_test_database(UNIVERSE_TEST_DATABASE_URL, "SPOIN_UNIVERSE_TEST_DATABASE_URL")

    engine = create_async_engine(UNIVERSE_TEST_DATABASE_URL)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await connection.run_sync(UniverseBase.metadata.drop_all)
            await connection.run_sync(UniverseBase.metadata.create_all)
    except Exception as exc:  # pragma: no cover - environment dependent
        await engine.dispose()
        pytest.skip(f"Corpus database unavailable: {exc}")

    yield async_sessionmaker(engine, expire_on_commit=False)

    await engine.dispose()


@pytest_asyncio.fixture
async def universe_session(
    universe_sessions: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with universe_sessions() as db:
        yield db


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
                canonical_title=f"{difficulty.value} card {n}",
                summary="hook",
                body="body",
            )
            session.add(card)
            cards.append(card)

    await session.flush()
    session.add_all([CardStats(card_id=card.id) for card in cards])
    await session.flush()

    return {"user": user, "topic": topic, "cards": cards}


#: The card-type budget every projected test subtopic-tier gets. Sums to
#: `_FAKE_TARGET_CARDS` and spreads across all five types, so a test exercising the
#: quota round-robin sees every type exactly as it did when the deleted
#: `FakeContentGenerator.generate_curriculum` produced these numbers.
_FAKE_QUOTAS = {"prose": 2, "code": 2, "diagram": 2, "comparison": 2, "ascii": 2}
_FAKE_TARGET_CARDS = 10


async def project_fake_curriculum(
    session: AsyncSession,
    topic: Topic,
    settings: Settings,
    *,
    groups: int = 3,
) -> list[Subtopic]:
    """Write the `Subtopic` rows `make curriculum-project` would, for one topic.

    Curricula are authored and projected, never generated (ADR-0007,
    docs/architecture/authored-curriculum.md), so a topic no longer arrives at the
    pipeline with nothing and gets a curriculum invented for it -- `resolve_and_plan_topic`
    now *requires* a projected one. Every integration test that used to lean on
    `FakeContentGenerator.generate_curriculum` calls this instead.

    The shape is deliberately identical to what that deleted method produced -- three
    groups, all three tiers each, `target_cards=10`, the same five-way quota -- so the
    card counts, quota accounting and dedup behaviour these tests assert on are testing
    the same pipeline they always did, not a new fixture's arithmetic.

    `min_cards` comes from `settings.min_cards_fraction` for the same reason the real
    projection reads it: one place decides what coverage means.
    """

    created: list[Subtopic] = []
    for index in range(groups):
        group_id = uuid.uuid4()
        for difficulty in Difficulty:
            subtopic = Subtopic(
                topic_id=topic.id,
                subtopic_group_id=group_id,
                difficulty=difficulty,
                title=f"{topic.canonical_name}: part {index + 1}",
                description=(
                    f"Placeholder curriculum slot {index + 1} for {topic.canonical_name}."
                ),
                target_cards=_FAKE_TARGET_CARDS,
                min_cards=max(1, round(_FAKE_TARGET_CARDS * settings.min_cards_fraction)),
                card_type_quotas=dict(_FAKE_QUOTAS),
                position=index,
            )
            session.add(subtopic)
            created.append(subtopic)

    #: The stamp is what `resolve_and_plan_topic` reads to decide a curriculum exists.
    topic.curriculum_generated_at = datetime.now(UTC)
    await session.flush()
    return created
