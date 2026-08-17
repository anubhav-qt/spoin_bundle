"""End-to-end tests for the LangGraph generation pipeline (ADR-0024/0025/0026).

Uses the real `session` fixture (Postgres + pgvector, skipped if unavailable) since
topic matching needs real cosine-distance queries — a `FakeContentGenerator` stands
in for the LLM, so no network/quota is involved.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spoin.core.config import Settings
from spoin.domain.enums import RejectionStage
from spoin.domain.models import Card, Question, RejectedCard, Subtopic, Topic, TopicAlias
from spoin.embeddings import HashEmbedder
from spoin.generation.base import BatchResult, ContentGenerator
from spoin.generation.fake import FakeContentGenerator
from spoin.generation.pipeline import (
    TopicRequest,
    match_and_create_topics,
    run_generation_pipeline,
)


async def _plan_and_generate(
    session: AsyncSession,
    settings: Settings,
    *names: str,
    generator: ContentGenerator | None = None,
) -> dict[str, object]:
    """Test convenience: run both phases in one (transaction-per-call semantics
    don't matter for these tests — only production's worker/CLI care about
    committing between them, see pipeline.py's module docstring)."""

    generator = generator if generator is not None else FakeContentGenerator()
    embedder = HashEmbedder(settings.embedding_dim)
    requests = [TopicRequest(name=name, description="") for name in names]

    outcomes = await match_and_create_topics(
        session, generator, embedder, settings, topic_requests=requests
    )
    new_topic_ids = [
        uuid.UUID(outcome["topic_id"]) for outcome in outcomes if not outcome["matched_existing"]
    ]
    generation_report = await run_generation_pipeline(
        session, generator, embedder, settings, topic_ids=new_topic_ids
    )
    generated_by_id = {t["topic_id"]: t for t in generation_report["topics"]}  # type: ignore[index]

    topics = []
    for outcome in outcomes:
        if outcome["matched_existing"]:
            topics.append(
                {
                    "topic_id": outcome["topic_id"],
                    "topic_name": outcome["topic_name"],
                    "merged_into_existing": True,
                    "accepted": 0,
                    "rejected": 0,
                }
            )
        else:
            report = dict(generated_by_id[outcome["topic_id"]])
            report["merged_into_existing"] = False
            topics.append(report)
    return {"topics": topics}


async def test_fresh_topic_generates_cards_dual_titles_and_questions(
    session: AsyncSession, settings: Settings
) -> None:
    report = await _plan_and_generate(session, settings, "Photosynthesis")
    (topic_report,) = report["topics"]

    assert topic_report["merged_into_existing"] is False
    assert topic_report["accepted"] > 0
    assert topic_report["rejected"] == 0
    assert topic_report["questions_accepted"] > 0

    cards = (
        await session.execute(select(Card).where(Card.topic_id == topic_report["topic_id"]))
    ).scalars().all()
    assert len(cards) == topic_report["accepted"]
    for card in cards:
        assert card.canonical_title  # ADR-0022: always present
        assert card.status.value == "active"
        assert card.content_embedding is not None

    questions = (
        await session.execute(
            select(Question).join(Card, Card.id == Question.card_id).where(
                Card.topic_id == topic_report["topic_id"]
            )
        )
    ).scalars().all()
    assert len(questions) == topic_report["questions_accepted"]
    for question in questions:
        assert question.card_id in {card.id for card in cards}


async def test_rerun_skips_curriculum_and_does_not_duplicate(
    session: AsyncSession, settings: Settings
) -> None:
    first = await _plan_and_generate(session, settings, "Rust Ownership")
    second = await _plan_and_generate(session, settings, "Rust Ownership")

    first_topic = first["topics"][0]
    second_topic = second["topics"][0]

    assert first_topic["merged_into_existing"] is False
    assert second_topic["merged_into_existing"] is True
    assert first_topic["topic_id"] == second_topic["topic_id"]
    # Matched onto the existing topic — no generation ran a second time.
    assert second_topic["accepted"] == 0

    subtopics = (
        await session.execute(select(Subtopic).where(Subtopic.topic_id == first_topic["topic_id"]))
    ).scalars().all()
    assert len(subtopics) > 0


async def test_independent_topics_in_one_run_do_not_cross_contaminate(
    session: AsyncSession, settings: Settings
) -> None:
    report = await _plan_and_generate(session, settings, "Quantum Computing", "Sourdough Baking")
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
    report = await _plan_and_generate(session, settings, "Thermodynamics")
    topic_id = report["topics"][0]["topic_id"]

    subtopics = (
        await session.execute(select(Subtopic).where(Subtopic.topic_id == topic_id))
    ).scalars().all()
    for subtopic in subtopics:
        expected = max(1, round(subtopic.target_cards * settings.min_cards_fraction))
        assert subtopic.min_cards == expected


async def test_exact_repeat_name_auto_merges_via_batched_match(
    session: AsyncSession, settings: Settings
) -> None:
    await _plan_and_generate(session, settings, "Kubernetes")
    report = await _plan_and_generate(session, settings, "Kubernetes")
    topic_report = report["topics"][0]

    assert topic_report["merged_into_existing"] is True
    alias = await session.scalar(
        select(TopicAlias).where(TopicAlias.normalized_text == "kubernetes")
    )
    assert alias is not None
    assert alias.decided_by == "llm_batch_match"


async def test_unrelated_topics_do_not_auto_merge(session: AsyncSession, settings: Settings) -> None:
    report = await _plan_and_generate(session, settings, "Photosynthesis", "Rust Ownership")
    for topic_report in report["topics"]:
        assert topic_report["merged_into_existing"] is False

    topics = (await session.execute(select(Topic))).scalars().all()
    assert len(topics) == 2


async def test_first_topic_ever_skips_the_llm_call_when_no_candidates_exist(
    session: AsyncSession, settings: Settings
) -> None:
    """No existing topics at all -> nothing to possibly match -> match_topics
    is never called (ADR-0025's "not a judgment call" case)."""

    generator = FakeContentGenerator()
    embedder = HashEmbedder(settings.embedding_dim)
    calls: list[object] = []
    original = generator.match_topics

    async def _tracking_match_topics(queries):  # type: ignore[no-untyped-def]
        calls.append(queries)
        return await original(queries)

    generator.match_topics = _tracking_match_topics  # type: ignore[method-assign]

    outcomes = await match_and_create_topics(
        session,
        generator,
        embedder,
        settings,
        topic_requests=[TopicRequest(name="Brand New Topic", description="")],
    )

    assert calls == []
    assert outcomes[0]["matched_existing"] is False


async def test_verification_rejection_is_persisted_to_rejected_card(
    session: AsyncSession, settings: Settings
) -> None:
    """ADR-0030: pass 2 can reject, and a rejection is stored, never silently
    dropped."""

    generator = FakeContentGenerator(reject_one_per_verify_batch=True)
    report = await _plan_and_generate(session, settings, "Cell Biology", generator=generator)
    topic_report = report["topics"][0]

    assert topic_report["rejected"] > 0

    rejected_rows = (
        await session.execute(
            select(RejectedCard).where(RejectedCard.topic_id == topic_report["topic_id"])
        )
    ).scalars().all()
    assert len(rejected_rows) > 0
    assert all(row.stage == RejectionStage.VERIFICATION for row in rejected_rows)
    assert all(row.reason for row in rejected_rows)
    # A rejected draft never becomes an active Card, ever, for the same family.
    active_bodies = {
        card.body
        for card in (
            await session.execute(select(Card).where(Card.topic_id == topic_report["topic_id"]))
        ).scalars().all()
    }
    assert not active_bodies & {row.body for row in rejected_rows}


class _DuplicateCardsGenerator(FakeContentGenerator):
    """Forces an exact intra-batch near-duplicate: the second card in every
    `generate_cards` batch of >=2 gets the first card's body verbatim, so the
    dedup running-set check (ADR-0030) has something real to catch."""

    async def generate_cards(self, **kwargs: object) -> BatchResult:  # type: ignore[override]
        result = await super().generate_cards(**kwargs)  # type: ignore[arg-type]
        if len(result.items) >= 2:
            items = list(result.items)
            items[1] = items[1].model_copy(update={"body": items[0].body})
            result = BatchResult(items=items, failures=result.failures)
        return result


async def test_near_duplicate_cards_are_rejected_and_persisted(
    session: AsyncSession, settings: Settings
) -> None:
    report = await _plan_and_generate(
        session, settings, "Marine Biology", generator=_DuplicateCardsGenerator()
    )
    topic_report = report["topics"][0]

    assert topic_report["rejected"] > 0

    rejected_rows = (
        await session.execute(
            select(RejectedCard).where(
                RejectedCard.topic_id == topic_report["topic_id"],
                RejectedCard.stage == RejectionStage.NEAR_DUPLICATE,
            )
        )
    ).scalars().all()
    assert len(rejected_rows) > 0


class _RecordingDuplicateGenerator(FakeContentGenerator):
    """Forces exactly one intra-batch near-duplicate on its FIRST
    `generate_cards` call only (so the topic's first run produces a real
    `rejected_card` row), and records every call's `avoid_bodies` kwarg so a
    later run can be asserted to have seen it."""

    def __init__(self) -> None:
        super().__init__()
        self.avoid_bodies_seen: list[list[str]] = []
        self._forced = False

    async def generate_cards(self, **kwargs: object) -> BatchResult:  # type: ignore[override]
        self.avoid_bodies_seen.append(list(kwargs["avoid_bodies"]))  # type: ignore[arg-type]
        result = await super().generate_cards(**kwargs)  # type: ignore[arg-type]
        if not self._forced and len(result.items) >= 2:
            self._forced = True
            items = list(result.items)
            items[1] = items[1].model_copy(update={"body": items[0].body})
            result = BatchResult(items=items, failures=result.failures)
        return result


async def test_rejected_duplicate_body_feeds_forward_into_next_run(
    session: AsyncSession, settings: Settings
) -> None:
    """ADR-0030 addendum: a near-duplicate rejection is fed back as
    `avoid_bodies` on the NEXT run's `generate_cards` call for the same
    subtopic-tier, so the writer sees the actual rejected content."""

    generator = _RecordingDuplicateGenerator()
    embedder = HashEmbedder(settings.embedding_dim)
    outcomes = await match_and_create_topics(
        session, generator, embedder, settings,
        topic_requests=[TopicRequest(name="Ornithology", description="")],
    )
    topic_id = uuid.UUID(outcomes[0]["topic_id"])

    await run_generation_pipeline(session, generator, embedder, settings, topic_ids=[topic_id])

    rejected_rows = (
        await session.execute(
            select(RejectedCard).where(
                RejectedCard.topic_id == topic_id, RejectedCard.stage == RejectionStage.NEAR_DUPLICATE
            )
        )
    ).scalars().all()
    assert len(rejected_rows) > 0
    rejected_body = rejected_rows[0].body

    calls_before = len(generator.avoid_bodies_seen)
    second_report = await run_generation_pipeline(
        session, generator, embedder, settings, topic_ids=[topic_id]
    )
    # The under-target subtopic actually got topped up in this second run.
    assert second_report["topics"][0]["accepted"] > 0  # type: ignore[index]

    calls_after = generator.avoid_bodies_seen[calls_before:]
    assert any(rejected_body in seen for seen in calls_after)
