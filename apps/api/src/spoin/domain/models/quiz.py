"""Quizzes and progression (ADR-0009).

Difficulty is **earned, not chosen**. The user picks only their entry tier, and
entering above beginner means passing that tier's quiz — the same quiz, used as a
placement test. One mechanism, three uses.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from spoin.core.config import get_settings
from spoin.domain.base import Base, CreatedAt, Timestamps, UUIDPrimaryKey, pg_enum
from spoin.domain.enums import Difficulty, QuestionKind, QuestionStatus, QuizKind

_EMBEDDING_DIM = get_settings().embedding_dim


class Question(Base, UUIDPrimaryKey, CreatedAt):
    """Generated FROM A CARD, never from the topic in the abstract.

    Three consequences, all load-bearing: the quiz can only test what the corpus
    actually teaches; every wrong answer links to the card that teaches it; and the
    bank is large enough that repeat attempts genuinely differ.
    """

    __tablename__ = "question"
    __table_args__ = (
        Index("ix_question_subtopic_id_status", "subtopic_id", "status"),
        CheckConstraint(
            "(kind = 'mcq' AND options IS NOT NULL AND correct_index IS NOT NULL)"
            " OR (kind = 'free_text' AND rubric IS NOT NULL)",
            name="kind_fields_present",
        ),
    )

    subtopic_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("subtopic.id", ondelete="CASCADE"), nullable=False
    )
    #: The source card. This is what makes remediation and coverage possible.
    card_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("card.id", ondelete="CASCADE"), nullable=False
    )
    difficulty: Mapped[Difficulty] = mapped_column(
        pg_enum(Difficulty, "difficulty"), nullable=False
    )
    kind: Mapped[QuestionKind] = mapped_column(
        pg_enum(QuestionKind, "question_kind"), nullable=False
    )

    stem: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    correct_index: Mapped[int | None] = mapped_column(Integer)

    #: Explicit 0-3 levels, not a vibe. Users retake quizzes and compare scores;
    #: inconsistent grading between attempts destroys trust faster than harsh
    #: grading does.
    rubric: Mapped[str | None] = mapped_column(Text)
    reference_answer: Mapped[str | None] = mapped_column(Text)
    explanation: Mapped[str | None] = mapped_column(Text)

    status: Mapped[QuestionStatus] = mapped_column(
        pg_enum(QuestionStatus, "question_status"), default=QuestionStatus.DRAFT, nullable=False
    )
    embedding: Mapped[list[float] | None] = mapped_column(Vector(_EMBEDDING_DIM))
    #: Always cloud + strongest model. A wrong answer key is worse than a wrong
    #: card: a bad card teaches something incorrect, a bad key tells a user they
    #: are wrong when they are right, which destroys trust in the whole system.
    gen_meta: Mapped[dict[str, object]] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), default=dict, nullable=False
    )


class UserQuestionSeen(Base, CreatedAt):
    """Questions-seen, tracked per user exactly like cards-seen, so retries draw
    fresh questions from the bank."""

    __tablename__ = "user_question_seen"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("question.id", ondelete="CASCADE"), primary_key=True
    )


class QuizAttempt(Base, UUIDPrimaryKey, CreatedAt):
    __tablename__ = "quiz_attempt"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    topic_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("topic.id", ondelete="CASCADE"), nullable=False
    )
    difficulty: Mapped[Difficulty] = mapped_column(
        pg_enum(Difficulty, "difficulty"), nullable=False
    )
    kind: Mapped[QuizKind] = mapped_column(pg_enum(QuizKind, "quiz_kind"), nullable=False)

    #: Weighted 70% MCQ / 30% free text. Equal weighting across ten items would
    #: make the written answer 10% of the grade, which defeats including it.
    score: Mapped[float | None] = mapped_column(Float)
    passed: Mapped[bool | None] = mapped_column(Boolean)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: MCQ results are returned immediately while the written answer is still being
    #: graded, so the user is never blocked on a spinner for the whole quiz.
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    graded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class QuizAttemptQuestion(Base, CreatedAt):
    __tablename__ = "quiz_attempt_question"

    attempt_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("quiz_attempt.id", ondelete="CASCADE"), primary_key=True
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("question.id", ondelete="CASCADE"), primary_key=True
    )
    #: Server-side length cap applies before this is stored (~2,000 words). Nominally
    #: unlimited, capped generously so a pasted 50k-word answer cannot blow the
    #: context window and fail the request.
    user_answer: Mapped[str | None] = mapped_column(Text)
    correct: Mapped[bool | None] = mapped_column(Boolean)
    rubric_level: Mapped[int | None] = mapped_column(Integer)
    #: The grader's justification, kept so grading can be audited when a user
    #: disputes a score — and sanity-checked for actually referencing the question,
    #: which is part of the prompt-injection defence.
    justification: Mapped[str | None] = mapped_column(Text)


class UserTopicProgress(Base, Timestamps):
    """Per-user, per-topic progression state.

    `tier_unlocked` is LATCHED and never recomputed. Recomputing would let
    background generation silently revoke earned progress: a user at 8/10 cards
    (80%, unlocked) drops to 8/20 (40%, locked) the moment ten more cards are
    generated. Losing an earned unlock to invisible background work is
    unacceptable, so once earned it is written here permanently.
    """

    __tablename__ = "user_topic_progress"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    topic_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("topic.id", ondelete="CASCADE"), primary_key=True
    )

    current_difficulty: Mapped[Difficulty] = mapped_column(
        pg_enum(Difficulty, "difficulty"), default=Difficulty.BEGINNER, nullable=False
    )

    # Three booleans each, indexed by Difficulty.rank. Arrays rather than nine
    # columns because they are always read as a set.
    #
    # This is the QUIZ unlock latch — "has this user covered 80% of every subtopic
    # in that tier" — not "may this user read that tier". Which tier they are
    # reading is `current_difficulty`. Defaulting beginner to True conflates the
    # two and reports a quiz as ready before the user has read anything.
    tier_unlocked: Mapped[list[bool]] = mapped_column(
        ARRAY(Boolean), default=lambda: [False, False, False], nullable=False
    )
    tier_content_complete: Mapped[list[bool]] = mapped_column(
        ARRAY(Boolean), default=lambda: [False, False, False], nullable=False
    )
    tier_quiz_passed: Mapped[list[bool]] = mapped_column(
        ARRAY(Boolean), default=lambda: [False, False, False], nullable=False
    )

    #: mastered = tier_content_complete[advanced] AND tier_quiz_passed[advanced].
    #: Permanent once set — never revoked by a later failed attempt.
    mastered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    #: After completion the topic enters revisit mode: seen cards are re-served at
    #: the user's tier, with the completion state shown honestly rather than
    #: disguised as new content.
    revisit_mode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class GenerationJob(Base, UUIDPrimaryKey, Timestamps):
    """A unit of generation work.

    The uniqueness key is `subtopic_id` (ADR-0007's amendment to ADR-0006). Two
    things fall out of that single choice: concurrent misses on the same starved
    slot collapse into one job instead of fifty spending a whole day of quota, and
    calls to the same subtopic stay sequential so each prompt sees the titles the
    previous one produced.
    """

    __tablename__ = "generation_job"
    __table_args__ = (
        # The coalescing lock. Partial-unique on the pending states, so one
        # subtopic can have at most one outstanding job while completed history is
        # retained. Without this the first popular topic exhausts the daily budget.
        Index(
            "uq_generation_job_subtopic_pending",
            "subtopic_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'running')"),
        ),
        Index("ix_generation_job_status_priority", "status", "priority"),
    )

    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # curriculum | cards | questions
    topic_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("topic.id", ondelete="CASCADE"), nullable=False
    )
    subtopic_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("subtopic.id", ondelete="CASCADE")
    )

    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    #: Higher runs first. Work is prioritised, not FIFO (ADR-0003 §6): refilling a
    #: starved popular topic outranks one user's niche custom topic, and a
    #: demand-triggered fill (a real user is waiting) outranks speculative
    #: background work. When quota runs out, low-priority work waits for tomorrow
    #: rather than everyone starving equally.
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class QuotaLedger(Base, Timestamps):
    """The quota governor's book (ADR-0003 §6).

    A real component, not a try/except: it tracks spend against a daily ceiling,
    enforces a hard stop, and degrades gracefully rather than erroring.
    """

    __tablename__ = "quota_ledger"

    day: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    #: Free text, not an enum — for a multi-key backend (rotating Gemini keys) this
    #: is `"gemini:{key_index}"`, one ledger row per key per day, no schema change
    #: needed to add key-awareness on top of the original single-backend design.
    backend: Mapped[str] = mapped_column(String(64), primary_key=True)
    requests_spent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    #: Set once, the moment this row's count reaches that day's target — never
    #: reset. Explicit rather than inferred from `updated_at` (a plain "last
    #: touched" timestamp doesn't distinguish "still has headroom" from "just hit
    #: the wall"), so a caller can query "which key ran out, and when" directly.
    exhausted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
