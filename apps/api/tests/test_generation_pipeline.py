"""End-to-end tests for the LangGraph generation pipeline (ADR-0024).

Uses the real `session` fixture (Postgres + pgvector, skipped if unavailable) since
the pipeline's topic-resolution step needs real cosine-distance queries — a
`FakeContentGenerator` stands in for the LLM, so no network/quota is involved.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spoin.core.config import Settings
from spoin.domain.models import Card, Subtopic, Topic, TopicAlias
from spoin.embeddings import HashEmbedder
from spoin.generation.fake import FakeContentGenerator
from spoin.generation.pipeline import TopicRequest, run_generation_pipeline


async def _run(session: AsyncSession, settings: Settings, *names: str) -> dict[str, object]:
    generator = FakeContentGenerator()
    embedder = HashEmbedder(settings.embedding_dim)
    requests = [TopicRequest(name=name, description="") for name in names]
    return await run_generation_pipeline(
        session, generator, embedder, settings, topic_requests=requests
    )


async def test_fresh_topic_generates_cards_and_dual_titles(
    session: AsyncSession, settings: Settings
) -> None:
    report = await _run(session, settings, "Photosynthesis")
    (topic_report,) = report["topics"]

    assert topic_report["merged_into_existing"] is False
    assert topic_report["accepted"] > 0
    assert topic_report["rejected"] == 0

    cards = (
        await session.execute(select(Card).where(Card.topic_id == topic_report["topic_id"]))
    ).scalars().all()
    assert len(cards) == topic_report["accepted"]
    for card in cards:
        assert card.canonical_title  # ADR-0022: always present
        assert card.status.value == "active"
        assert card.content_embedding is not None


async def test_rerun_skips_curriculum_and_does_not_duplicate(
    session: AsyncSession, settings: Settings
) -> None:
    first = await _run(session, settings, "Rust Ownership")
    second = await _run(session, settings, "Rust Ownership")

    first_topic = first["topics"][0]
    second_topic = second["topics"][0]

    assert first_topic["merged_into_existing"] is False
    assert second_topic["merged_into_existing"] is True
    assert first_topic["topic_id"] == second_topic["topic_id"]
    # Already at target on the second pass — no new curriculum call, no new cards.
    assert second_topic["accepted"] == 0

    subtopics = (
        await session.execute(select(Subtopic).where(Subtopic.topic_id == first_topic["topic_id"]))
    ).scalars().all()
    # Same subtopic set both times, not doubled.
    assert len(subtopics) == len(first_topic["subtopics"])


async def test_independent_topics_in_one_run_do_not_cross_contaminate(
    session: AsyncSession, settings: Settings
) -> None:
    report = await _run(session, settings, "Quantum Computing", "Sourdough Baking")
    names = {t["topic_name"] for t in report["topics"]}
    ids = {t["topic_id"] for t in report["topics"]}

    assert names == {"Quantum Computing", "Sourdough Baking"}
    assert len(ids) == 2  # distinct topics, neither merged into the other
    for topic_report in report["topics"]:
        assert topic_report["merged_into_existing"] is False
        assert topic_report["accepted"] > 0


async def test_min_cards_derived_from_fraction_setting(
    session: AsyncSession, settings: Settings
) -> None:
    report = await _run(session, settings, "Thermodynamics")
    topic_id = report["topics"][0]["topic_id"]

    subtopics = (
        await session.execute(select(Subtopic).where(Subtopic.topic_id == topic_id))
    ).scalars().all()
    for subtopic in subtopics:
        expected = max(1, round(subtopic.target_cards * settings.min_cards_fraction))
        assert subtopic.min_cards == expected


async def test_exact_repeat_name_auto_merges_via_high_similarity(
    session: AsyncSession, settings: Settings
) -> None:
    await _run(session, settings, "Kubernetes")
    report = await _run(session, settings, "Kubernetes")
    topic_report = report["topics"][0]

    assert topic_report["merged_into_existing"] is True
    alias = await session.scalar(
        select(TopicAlias).where(TopicAlias.normalized_text == "kubernetes")
    )
    assert alias is not None
    assert alias.decided_by == "auto_merge"


async def test_unrelated_topics_do_not_auto_merge(session: AsyncSession, settings: Settings) -> None:
    report = await _run(session, settings, "Photosynthesis", "Rust Ownership")
    for topic_report in report["topics"]:
        assert topic_report["merged_into_existing"] is False

    topics = (await session.execute(select(Topic))).scalars().all()
    assert len(topics) == 2
