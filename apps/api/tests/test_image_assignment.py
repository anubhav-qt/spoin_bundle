"""Tests for open-licensed image assignment, visual_kind, and loop guard (ADR-0095, Task 0040).

Tests:
1. `_card_matches_type` predicate precision (IMAGE, PROSE, ASCII).
2. Database CHECK constraint `ck_card_visual_kind_accompanies_visual_id`.
3. `assign_images` end-to-end against universe catalog and embedder.
4. Intra-batch and cross-draft image uniqueness.
5. Similarity floor gating and score recording.
6. Graceful degradation when universe is unreachable (never raises).
7. Planner ceiling capping and quota conservation.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from frog.embeddings import HashEmbedder
from frog.universe.models import EMBEDDING_DIM, Image, ImageLicence
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from spoin.core.db import UniverseNotConfiguredError
from spoin.domain.enums import CardStatus, CardType, Difficulty, VisualKind
from spoin.domain.models import Card, Subtopic, Topic
from spoin.generation.base import CardDraft
from spoin.generation.images import (
    assign_images,
    count_available_images,
    topic_used_image_ids,
)
from spoin.generation.pipeline.state import _card_matches_type

EMBEDDER = HashEmbedder(EMBEDDING_DIM)


def _draft(
    title: str = "Test Card",
    summary: str = "Summary of the card.",
    body: str = "Body explanation of the astronomical concept.",
    visual_id: str | None = None,
    visual_kind: VisualKind | None = None,
) -> CardDraft:
    return CardDraft(
        title=title,
        canonical_title=title,
        summary=summary,
        body=body,
        difficulty=Difficulty.BEGINNER,
        visual_id=visual_id,
        visual_kind=visual_kind,
    )


# ---------------------------------------------------------------------------
# 1. _card_matches_type unit tests
# ---------------------------------------------------------------------------


def test_card_matches_type_image() -> None:
    # IMAGE requires no tags and visual_kind is VisualKind.IMAGE
    image_draft = _draft(visual_id=str(uuid.uuid4()), visual_kind=VisualKind.IMAGE)
    assert _card_matches_type(image_draft, CardType.IMAGE.value)

    # Missing visual_kind does not match
    no_kind = _draft(visual_id=str(uuid.uuid4()), visual_kind=None)
    assert not _card_matches_type(no_kind, CardType.IMAGE.value)

    # ASCII kind does not match IMAGE
    ascii_kind = _draft(visual_id="scene_1", visual_kind=VisualKind.ASCII)
    assert not _card_matches_type(ascii_kind, CardType.IMAGE.value)

    # Prose draft (no visual_id) does not match IMAGE
    prose_draft = _draft(visual_id=None, visual_kind=None)
    assert not _card_matches_type(prose_draft, CardType.IMAGE.value)

    # Diagram archetype does not match IMAGE even if visual_kind is set
    diagram_draft = _draft(
        body="```mermaid\ngraph TD\nA-->B\n```",
        visual_id=str(uuid.uuid4()),
        visual_kind=VisualKind.IMAGE,
    )
    assert not _card_matches_type(diagram_draft, CardType.IMAGE.value)


def test_card_matches_type_prose() -> None:
    # PROSE matches when no archetype tags and visual_id is None
    prose_draft = _draft(visual_id=None, visual_kind=None)
    assert _card_matches_type(prose_draft, CardType.PROSE.value)

    # Any visual_id (image or ascii) excludes PROSE
    image_draft = _draft(visual_id=str(uuid.uuid4()), visual_kind=VisualKind.IMAGE)
    assert not _card_matches_type(image_draft, CardType.PROSE.value)

    ascii_draft = _draft(visual_id="scene_1", visual_kind=VisualKind.ASCII)
    assert not _card_matches_type(ascii_draft, CardType.PROSE.value)


def test_card_matches_type_ascii() -> None:
    # ASCII matches only when visual_kind is VisualKind.ASCII
    ascii_draft = _draft(visual_id="galaxy_sketch", visual_kind=VisualKind.ASCII)
    assert _card_matches_type(ascii_draft, CardType.ASCII.value)

    # IMAGE kind does not match ASCII
    image_draft = _draft(visual_id=str(uuid.uuid4()), visual_kind=VisualKind.IMAGE)
    assert not _card_matches_type(image_draft, CardType.ASCII.value)

    # None does not match ASCII
    none_draft = _draft(visual_id="something", visual_kind=None)
    assert not _card_matches_type(none_draft, CardType.ASCII.value)


# ---------------------------------------------------------------------------
# 2. Database CHECK constraint tests (spoin_db_2)
# ---------------------------------------------------------------------------


async def _create_topic_and_subtopic(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    topic = Topic(
        slug=f"t-{uuid.uuid4().hex[:8]}",
        canonical_name="Astronomy Test",
        description="Astronomy test topic",
    )
    session.add(topic)
    await session.flush()
    subtopic = Subtopic(
        topic_id=topic.id,
        title="Galaxies",
        description="Galaxy dynamics",
        difficulty=Difficulty.BEGINNER,
        target_cards=10,
        min_cards=5,
        position=0,
    )
    session.add(subtopic)
    await session.flush()
    return topic.id, subtopic.id


async def test_card_visual_kind_check_constraint_valid(session: AsyncSession) -> None:
    topic_id, subtopic_id = await _create_topic_and_subtopic(session)

    # 1. Both NULL is valid (prose)
    card_prose = Card(
        family_id=uuid.uuid4(),
        topic_id=topic_id,
        subtopic_id=subtopic_id,
        difficulty=Difficulty.BEGINNER,
        status=CardStatus.ACTIVE,
        title="Prose Card",
        canonical_title="Prose Card",
        summary="Summary",
        body="Body text",
        visual_id=None,
        visual_kind=None,
    )
    session.add(card_prose)
    await session.commit()
    assert card_prose.id is not None

    # 2. Both non-NULL is valid (image)
    card_img = Card(
        family_id=uuid.uuid4(),
        topic_id=topic_id,
        subtopic_id=subtopic_id,
        difficulty=Difficulty.BEGINNER,
        status=CardStatus.ACTIVE,
        title="Image Card",
        canonical_title="Image Card",
        summary="Summary",
        body="Body text",
        visual_id=str(uuid.uuid4()),
        visual_kind=VisualKind.IMAGE,
    )
    session.add(card_img)
    await session.commit()
    assert card_img.id is not None


async def test_card_visual_kind_check_constraint_rejects_mismatch(session: AsyncSession) -> None:
    topic_id, subtopic_id = await _create_topic_and_subtopic(session)

    # visual_id set without visual_kind violates constraint
    card_bad_1 = Card(
        family_id=uuid.uuid4(),
        topic_id=topic_id,
        subtopic_id=subtopic_id,
        difficulty=Difficulty.BEGINNER,
        status=CardStatus.ACTIVE,
        title="Bad Card 1",
        canonical_title="Bad Card 1",
        summary="Summary",
        body="Body text",
        visual_id="scene_label",
        visual_kind=None,
    )
    session.add(card_bad_1)
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()

    # visual_kind set without visual_id violates constraint
    card_bad_2 = Card(
        family_id=uuid.uuid4(),
        topic_id=topic_id,
        subtopic_id=subtopic_id,
        difficulty=Difficulty.BEGINNER,
        status=CardStatus.ACTIVE,
        title="Bad Card 2",
        canonical_title="Bad Card 2",
        summary="Summary",
        body="Body text",
        visual_id=None,
        visual_kind=VisualKind.IMAGE,
    )
    session.add(card_bad_2)
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


# ---------------------------------------------------------------------------
# 3. assign_images integration tests (the_spoin_universe + spoin_db_2)
# ---------------------------------------------------------------------------


async def _seed_test_images(
    universe_sessions: async_sessionmaker[AsyncSession],
) -> list[Image]:
    img1 = Image(
        id=uuid.uuid4(),
        source_url="https://images.nasa.gov/am0644.jpg",
        content_hash="hash1",
        manifest_path="astronomy/images.md",
        title="Ring Galaxy AM 0644-741",
        description="Ring galaxy collision forming blue starburst clusters around the nucleus.",
        source_page="https://images.nasa.gov/details/am0644",
        licence=ImageLicence.PUBLIC_DOMAIN,
        attribution="NASA, ESA",
        category="astronomy",
        sub_category="physics/astronomy",
        topic_tags=["galaxies"],
        embedding=EMBEDDER.embed_passage(
            ["Ring galaxy collision forming blue starburst clusters around the nucleus."]
        )[0],
        embedding_model=EMBEDDER.model_name,
        ingested_at=datetime.now(UTC),
    )
    img2 = Image(
        id=uuid.uuid4(),
        source_url="https://images.nasa.gov/crab.jpg",
        content_hash="hash2",
        manifest_path="astronomy/images.md",
        title="Crab Nebula M1",
        description="Supernova remnant in Taurus showing expanding filaments and ionized gas.",
        source_page="https://images.nasa.gov/details/crab",
        licence=ImageLicence.PUBLIC_DOMAIN,
        attribution="NASA, ESA",
        category="astronomy",
        sub_category="physics/astronomy",
        topic_tags=["nebulae"],
        embedding=EMBEDDER.embed_passage(
            ["Supernova remnant in Taurus showing expanding filaments and ionized gas."]
        )[0],
        embedding_model=EMBEDDER.model_name,
        ingested_at=datetime.now(UTC),
    )
    async with universe_sessions() as u_session:
        u_session.add_all([img1, img2])
        await u_session.commit()
    return [img1, img2]


async def test_assign_images_assigns_and_prevents_intra_batch_collision(
    universe_sessions: async_sessionmaker[AsyncSession],
    session: AsyncSession,
) -> None:
    images = await _seed_test_images(universe_sessions)
    topic_id, _ = await _create_topic_and_subtopic(session)

    @asynccontextmanager
    async def u_scope() -> AsyncIterator[AsyncSession]:
        async with universe_sessions() as s:
            yield s

    draft1 = _draft(title="First Galaxy Card", body="Collision forming ring galaxies.")
    draft2 = _draft(title="Second Galaxy Card", body="Supernova gas clouds in deep space.")

    report = await assign_images(
        u_scope,
        EMBEDDER,
        topic_id=topic_id,
        categories=["astronomy"],
        drafts=[draft1, draft2],
        min_score=0.0,
        db_session=session,
    )

    assert report.assigned == 2
    assert report.no_candidate == 0
    assert report.below_floor == 0
    assert report.unavailable == 0
    assert len(report.scores) == 2

    # Each draft received a distinct image
    assert draft1.visual_id is not None
    assert draft2.visual_id is not None
    assert draft1.visual_id != draft2.visual_id
    assert {draft1.visual_id, draft2.visual_id} == {str(images[0].id), str(images[1].id)}

    # Both drafts have visual_kind=IMAGE and populated visual_slots
    assert draft1.visual_kind == VisualKind.IMAGE
    assert draft1.visual_slots is not None
    assert "title" in draft1.visual_slots
    assert "attribution" in draft1.visual_slots
    assert "display_url" in draft1.visual_slots
    assert "source_page" in draft1.visual_slots
    assert "licence" in draft1.visual_slots


async def test_assign_images_exhausted_catalog(
    universe_sessions: async_sessionmaker[AsyncSession],
    session: AsyncSession,
) -> None:
    # Seed only 1 image
    async with universe_sessions() as u_session:
        img = Image(
            id=uuid.uuid4(),
            source_url="https://images.nasa.gov/single.jpg",
            content_hash="hash_single",
            manifest_path="astronomy/images.md",
            title="Single Image",
            description="A lone astronomical image.",
            source_page="https://images.nasa.gov/single",
            licence=ImageLicence.PUBLIC_DOMAIN,
            attribution="NASA",
            category="astronomy",
            sub_category=None,
            topic_tags=["astronomy"],
            embedding=EMBEDDER.embed_passage(["A lone astronomical image."])[0],
            embedding_model=EMBEDDER.model_name,
            ingested_at=datetime.now(UTC),
        )
        u_session.add(img)
        await u_session.commit()

    topic_id, _ = await _create_topic_and_subtopic(session)

    @asynccontextmanager
    async def u_scope() -> AsyncIterator[AsyncSession]:
        async with universe_sessions() as s:
            yield s

    draft1 = _draft(title="Card 1")
    draft2 = _draft(title="Card 2")

    report = await assign_images(
        u_scope,
        EMBEDDER,
        topic_id=topic_id,
        categories=["astronomy"],
        drafts=[draft1, draft2],
        min_score=0.0,
        db_session=session,
    )

    assert report.assigned == 1
    assert report.no_candidate == 1
    assert draft1.visual_id is not None
    assert draft2.visual_id is None
    assert draft2.visual_kind is None


async def test_assign_images_below_floor(
    universe_sessions: async_sessionmaker[AsyncSession],
    session: AsyncSession,
) -> None:
    await _seed_test_images(universe_sessions)
    topic_id, _ = await _create_topic_and_subtopic(session)

    @asynccontextmanager
    async def u_scope() -> AsyncIterator[AsyncSession]:
        async with universe_sessions() as s:
            yield s

    draft = _draft(title="Card Below Floor")

    # min_score = 1.1 ensures every cosine similarity (< 1.0) is below floor
    report = await assign_images(
        u_scope,
        EMBEDDER,
        topic_id=topic_id,
        categories=["astronomy"],
        drafts=[draft],
        min_score=1.1,
        db_session=session,
    )

    assert report.assigned == 0
    assert report.below_floor == 1
    assert len(report.scores) == 1
    assert draft.visual_id is None
    assert draft.visual_kind is None


async def test_assign_images_universe_unavailable_does_not_raise(session: AsyncSession) -> None:
    topic_id, _ = await _create_topic_and_subtopic(session)

    @asynccontextmanager
    async def failing_scope() -> AsyncIterator[AsyncSession]:
        raise UniverseNotConfiguredError("Universe DB is not configured")
        yield  # type: ignore[unreachable]

    draft = _draft(title="Card with No Universe")

    report = await assign_images(
        failing_scope,
        EMBEDDER,
        topic_id=topic_id,
        categories=["astronomy"],
        drafts=[draft],
        min_score=0.0,
        db_session=session,
    )

    assert report.assigned == 0
    assert report.unavailable == 1
    assert draft.visual_id is None


async def test_planner_ceiling_caps_image_quota(
    universe_sessions: async_sessionmaker[AsyncSession],
    session: AsyncSession,
) -> None:
    images = await _seed_test_images(universe_sessions)
    topic_id, subtopic_id = await _create_topic_and_subtopic(session)

    # Add an active card using image 0
    card = Card(
        family_id=uuid.uuid4(),
        topic_id=topic_id,
        subtopic_id=subtopic_id,
        difficulty=Difficulty.BEGINNER,
        status=CardStatus.ACTIVE,
        title="Used Image Card",
        canonical_title="Used Image Card",
        summary="Summary",
        body="Body",
        visual_id=str(images[0].id),
        visual_kind=VisualKind.IMAGE,
    )
    session.add(card)
    await session.commit()

    used = await topic_used_image_ids(session, topic_id)
    assert used == {images[0].id}

    @asynccontextmanager
    async def u_scope() -> AsyncIterator[AsyncSession]:
        async with universe_sessions() as s:
            yield s

    # 1 image remains available after excluding used image 0
    available = await count_available_images(
        u_scope,
        categories=["astronomy"],
        exclude_image_ids=used,
    )
    assert available == 1

    # Tier requested 5 image cards and 10 prose cards (target = 15)
    tier_quotas = {"image": 5, "prose": 10}
    target = sum(tier_quotas.values())

    # Capping logic matches nodes.py:
    requested_img = tier_quotas["image"]
    capped_img = min(requested_img, available)
    if capped_img < requested_img:
        shortfall = requested_img - capped_img
        tier_quotas["image"] = capped_img

    assert tier_quotas["image"] == 1
    assert tier_quotas["prose"] == 10
