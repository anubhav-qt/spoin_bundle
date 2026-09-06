"""Quiz backend: sampling, MCQ grading, free-text grading, progression
write-back (task 0011, part 2; ADR-0009 amended by ADR-0027).

Uses the real `session` fixture (Postgres + pgvector, skipped if unavailable).
Card/question generation goes through the real pipeline with
`FakeContentGenerator` + `HashEmbedder` (same pattern as
test_generation_pipeline.py) so the question bank is shaped exactly like
production — real MCQ/free-text split, real subtopic/difficulty structure —
without any network call.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from frog.embeddings import HashEmbedder
from frog.universe.models import EMBEDDING_DIM
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import project_fake_curriculum
from spoin.api.routers.quiz import start_quiz, submit_free_text, submit_mcq
from spoin.api.routers.topics import subscribe_topic
from spoin.api.schemas import (
    McqAnswerIn,
    QuizStartIn,
    QuizSubmitFreeTextIn,
    QuizSubmitMcqIn,
)
from spoin.core.config import Settings
from spoin.domain.enums import Difficulty
from spoin.domain.models import Question, Topic, User, UserTopicProgress
from spoin.generation.fake import FakeContentGenerator
from spoin.generation.pipeline import TopicRequest, match_and_create_topics, run_generation_pipeline


async def _make_topic_with_bank(session: AsyncSession, settings: Settings) -> uuid.UUID:
    generator = FakeContentGenerator()
    embedder = HashEmbedder(EMBEDDING_DIM)
    outcomes = await match_and_create_topics(
        session,
        generator,
        embedder,
        settings,
        topic_requests=[TopicRequest(name=f"Quiz Topic {uuid.uuid4().hex[:6]}", description="")],
    )
    topic_id = uuid.UUID(outcomes[0]["topic_id"])
    # Stands in for `make curriculum-project` -- the pipeline no longer generates a
    # curriculum, it requires a projected one (ADR-0007).
    topic = await session.get(Topic, topic_id)
    assert topic is not None
    await project_fake_curriculum(session, topic, settings)
    await session.commit()
    await run_generation_pipeline(session, generator, embedder, settings, topic_ids=[topic_id])
    return topic_id


async def _make_user(session: AsyncSession) -> uuid.UUID:
    user = User(email=f"{uuid.uuid4()}@test.local", display_name="Test")
    session.add(user)
    await session.flush()
    return user.id


async def test_entry_tier_is_trusted_and_unlocks_below_tiers(
    session: AsyncSession, settings: Settings
) -> None:
    topic_id = await _make_topic_with_bank(session, settings)
    user_id = await _make_user(session)

    topic_out = await subscribe_topic(
        topic_id, session, user_id, entry_difficulty=Difficulty.INTERMEDIATE
    )
    assert topic_out.current_difficulty == Difficulty.INTERMEDIATE

    progress = await session.scalar(
        select(UserTopicProgress).where(
            UserTopicProgress.user_id == user_id, UserTopicProgress.topic_id == topic_id
        )
    )
    assert progress is not None
    # ADR-0032 amends ADR-0027: only tiers STRICTLY BELOW the entry tier
    # pre-unlock. The entry tier itself (index 1, Intermediate) still earns
    # its own quiz through the normal coverage gate.
    assert progress.tier_unlocked == [True, False, False]

    # No content read yet, so the entry tier's own quiz is still gated by
    # the ordinary coverage requirement...
    with pytest.raises(HTTPException) as exc_info:
        await start_quiz(
            topic_id, QuizStartIn(difficulty=Difficulty.INTERMEDIATE), session, user_id
        )
    assert exc_info.value.status_code == 403

    # ...but a practice attempt at a tier BELOW the entry tier is open
    # immediately, no coverage required.
    start = await start_quiz(
        topic_id, QuizStartIn(difficulty=Difficulty.BEGINNER), session, user_id
    )
    assert start.kind == "placement"
    assert len(start.mcq) == settings.quiz_mcq_count


async def test_full_promotion_flow_advances_current_difficulty(
    session: AsyncSession, settings: Settings
) -> None:
    topic_id = await _make_topic_with_bank(session, settings)
    user_id = await _make_user(session)
    await subscribe_topic(topic_id, session, user_id, entry_difficulty=Difficulty.BEGINNER)

    # Force the coverage gate open directly rather than re-deriving the whole
    # seen-cards pipeline here -- that gate is topics.py's own concern
    # (test_topics_request.py doesn't re-verify it either); this test is about
    # what happens once a quiz is actually reachable.
    progress = await session.scalar(
        select(UserTopicProgress).where(
            UserTopicProgress.user_id == user_id, UserTopicProgress.topic_id == topic_id
        )
    )
    assert progress is not None
    progress.tier_unlocked = [True, False, False]
    await session.commit()

    start = await start_quiz(
        topic_id, QuizStartIn(difficulty=Difficulty.BEGINNER), session, user_id
    )
    assert start.kind == "promotion"
    assert len(start.mcq) == settings.quiz_mcq_count

    # Answer every MCQ correctly.
    correct_by_id = {
        q.id: q.correct_index
        for q in (
            await session.execute(
                select(Question).where(Question.id.in_([m.question_id for m in start.mcq]))
            )
        )
        .scalars()
        .all()
    }
    mcq_result = await submit_mcq(
        start.attempt_id,
        QuizSubmitMcqIn(
            answers=[
                McqAnswerIn(question_id=m.question_id, selected_index=correct_by_id[m.question_id])
                for m in start.mcq
            ]
        ),
        session,
        user_id,
    )
    assert mcq_result.mcq_score == 1.0

    ft_question = await session.get(Question, start.free_text.question_id)
    assert ft_question is not None
    final = await submit_free_text(
        start.attempt_id,
        QuizSubmitFreeTextIn(answer=ft_question.reference_answer or "a thorough, correct answer"),
        session,
        user_id,
    )

    assert final.passed is True
    assert final.progressed is True
    assert final.remediation == []

    await session.refresh(progress)
    assert progress.current_difficulty == Difficulty.INTERMEDIATE
    assert progress.tier_quiz_passed[Difficulty.BEGINNER.rank] is True


async def test_placement_attempt_never_changes_progression(
    session: AsyncSession, settings: Settings
) -> None:
    topic_id = await _make_topic_with_bank(session, settings)
    user_id = await _make_user(session)
    await subscribe_topic(topic_id, session, user_id, entry_difficulty=Difficulty.INTERMEDIATE)

    progress = await session.scalar(
        select(UserTopicProgress).where(
            UserTopicProgress.user_id == user_id, UserTopicProgress.topic_id == topic_id
        )
    )
    assert progress is not None
    before = progress.current_difficulty

    start = await start_quiz(
        topic_id, QuizStartIn(difficulty=Difficulty.BEGINNER), session, user_id
    )
    assert start.kind == "placement"

    # Correct or not doesn't matter for this test — only that it never
    # touches progression.
    mcq_answers = [McqAnswerIn(question_id=m.question_id, selected_index=0) for m in start.mcq]
    await submit_mcq(start.attempt_id, QuizSubmitMcqIn(answers=mcq_answers), session, user_id)

    final = await submit_free_text(
        start.attempt_id, QuizSubmitFreeTextIn(answer="whatever"), session, user_id
    )
    assert final.progressed is False

    await session.refresh(progress)
    assert progress.current_difficulty == before


async def test_thin_bank_returns_conflict(session: AsyncSession, settings: Settings) -> None:
    user_id = await _make_user(session)
    topic = Topic(slug=f"empty-{uuid.uuid4().hex[:8]}", canonical_name="Empty Topic")
    session.add(topic)
    await session.flush()
    await subscribe_topic(topic.id, session, user_id, entry_difficulty=Difficulty.BEGINNER)

    # ADR-0032: Beginner entry starts fully locked -- force the tier open so
    # this test exercises the thin-bank check, not the unlock gate.
    progress = await session.scalar(
        select(UserTopicProgress).where(
            UserTopicProgress.user_id == user_id, UserTopicProgress.topic_id == topic.id
        )
    )
    assert progress is not None
    progress.tier_unlocked = [True, False, False]
    await session.commit()

    with pytest.raises(HTTPException) as exc_info:
        await start_quiz(topic.id, QuizStartIn(difficulty=Difficulty.BEGINNER), session, user_id)
    assert exc_info.value.status_code == 409
