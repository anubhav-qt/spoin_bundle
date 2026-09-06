"""The deterministic projection: universe curriculum tables -> Topic/Subtopic.

Both databases are real (`spoin_db_test` and `the_spoin_universe_test`) because what is
under test is cross-database behaviour and the CASCADE that drops a removed subtopic's
cards. Skipped when either test database is unset.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from frog.curriculum.models import Curriculum, CurriculumSubtopic
from frog.embeddings import HashEmbedder
from frog.universe.models import EMBEDDING_DIM
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import spoin.curriculum.projection as projection_module
from spoin.curriculum.projection import ProjectionReport, project_curricula
from spoin.domain.enums import CardStatus, Difficulty
from spoin.domain.models import Card, Subtopic, Topic, TopicAlias


async def _project() -> ProjectionReport:
    """`project_curricula` with the deterministic test embedder injected."""

    return await project_curricula(HashEmbedder(EMBEDDING_DIM))


@pytest_asyncio.fixture
async def bound(
    session: AsyncSession,
    universe_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[AsyncSession, AsyncSession]]:
    """Point `project_curricula`'s two session scopes at the test databases."""

    @asynccontextmanager
    async def product_scope() -> AsyncIterator[AsyncSession]:
        yield session  # the fixture owns commit/rollback

    @asynccontextmanager
    async def universe_scope() -> AsyncIterator[AsyncSession]:
        yield universe_session

    monkeypatch.setattr(projection_module, "session_scope", product_scope)
    monkeypatch.setattr(projection_module, "universe_session_scope", universe_scope)
    yield session, universe_session


async def _seed_curriculum(
    universe: AsyncSession,
    *,
    topic_name: str = "Rust",
    subtopics: list[dict] | None = None,
) -> None:
    curriculum = Curriculum(
        source_path=f"{topic_name.lower()}/curriculum.md",
        content_hash="hash",
        topic_name=topic_name,
        description="Systems programming",
        is_survey=False,
        ingested_at=func.now(),
    )
    universe.add(curriculum)
    await universe.flush()
    rows = subtopics or [
        {
            "title": "Ownership",
            "tiers": {
                "beginner": {"target_cards": 10, "card_types": {"prose": 7, "code": 3}},
                "intermediate": {"target_cards": 8, "card_types": {"prose": 5, "code": 3}},
            },
        },
        {
            "title": "Smart Pointers",
            "tiers": {"intermediate": {"target_cards": 6, "card_types": {"prose": 6}}},
        },
    ]
    for ordinal, row in enumerate(rows):
        universe.add(
            CurriculumSubtopic(
                curriculum_id=curriculum.id,
                ordinal=ordinal,
                title=row["title"],
                description=f"About {row['title']}",
                prerequisites=row.get("prerequisites", []),
                source_paths=["cs/x.md"],
                tiers=row["tiers"],
            )
        )
    await universe.commit()


@pytest.mark.asyncio
async def test_projects_a_new_topic_with_one_subtopic_per_tier(
    bound: tuple[AsyncSession, AsyncSession],
) -> None:
    session, universe = bound
    await _seed_curriculum(universe)

    report = await _project()
    assert report.topics_created == 1
    assert report.subtopics_upserted == 3  # 2 tiers + 1 tier

    topic = await session.scalar(select(Topic).where(Topic.slug == "rust"))
    assert topic is not None
    assert topic.canonical_name == "Rust"
    assert topic.is_survey is False
    assert topic.curriculum_generated_at is not None
    assert topic.curriculum_corpus_version is not None
    # Resolvable by ADR-0025 matching: it has an embedding and a canonical alias.
    assert topic.embedding is not None
    assert topic.embedding_model
    alias = await session.scalar(select(TopicAlias).where(TopicAlias.topic_id == topic.id))
    assert alias is not None
    assert alias.decided_by == "projection"

    subs = (
        (await session.execute(select(Subtopic).where(Subtopic.topic_id == topic.id)))
        .scalars()
        .all()
    )
    assert len(subs) == 3
    ownership = {s.difficulty: s for s in subs if s.title == "Ownership"}
    assert set(ownership) == {Difficulty.BEGINNER, Difficulty.INTERMEDIATE}
    # tiers of one concept share a group id
    assert ownership[Difficulty.BEGINNER].subtopic_group_id == (
        ownership[Difficulty.INTERMEDIATE].subtopic_group_id
    )
    beginner = ownership[Difficulty.BEGINNER]
    assert beginner.target_cards == 10
    assert beginner.min_cards == 6  # round(10 * 0.6)
    assert beginner.card_type_quotas == {"prose": 7, "code": 3}


@pytest.mark.asyncio
async def test_reprojection_is_idempotent(bound: tuple[AsyncSession, AsyncSession]) -> None:
    session, universe = bound
    await _seed_curriculum(universe)

    await _project()
    first_ids = set((await session.execute(select(Subtopic.id))).scalars().all())

    report = await _project()
    assert report.topics_created == 0
    assert report.topics_updated == 1
    assert report.subtopics_removed == 0
    assert set((await session.execute(select(Subtopic.id))).scalars().all()) == first_ids


@pytest.mark.asyncio
async def test_a_dropped_subtopic_is_removed_and_its_cards_cascade(
    bound: tuple[AsyncSession, AsyncSession],
) -> None:
    session, universe = bound
    await _seed_curriculum(universe)
    await _project()

    smart = await session.scalar(select(Subtopic).where(Subtopic.title == "Smart Pointers"))
    assert smart is not None
    session.add(
        Card(
            family_id=smart.id,  # any uuid
            topic_id=smart.topic_id,
            subtopic_id=smart.id,
            difficulty=Difficulty.INTERMEDIATE,
            status=CardStatus.ACTIVE,
            title="t",
            canonical_title="t",
            summary="s",
            body="b",
        )
    )
    await session.commit()

    # Re-seed the universe with the "Smart Pointers" subtopic gone.
    for row in (await universe.execute(select(Curriculum))).scalars().all():
        await universe.delete(row)
    await universe.commit()
    await _seed_curriculum(
        universe,
        subtopics=[
            {
                "title": "Ownership",
                "tiers": {
                    "beginner": {"target_cards": 10, "card_types": {"prose": 10}},
                },
            }
        ],
    )

    report = await _project()
    assert report.subtopics_removed == 2  # both Smart Pointers + Ownership/intermediate

    remaining = (await session.execute(select(Subtopic.title, Subtopic.difficulty))).all()
    assert remaining == [("Ownership", Difficulty.BEGINNER)]
    assert await session.scalar(select(func.count()).select_from(Card)) == 0
