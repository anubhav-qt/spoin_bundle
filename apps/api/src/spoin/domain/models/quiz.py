"""Quizzes and progression (ADR-0009).

Difficulty is **earned, not chosen**. The user picks only their entry tier, and
entering above beginner means passing that tier's quiz — the same quiz, used as a
placement test. One mechanism, three uses.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from frog.universe.models import EMBEDDING_DIM
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

from spoin.domain.base import Base, CreatedAt, Timestamps, UUIDPrimaryKey, pg_enum
from spoin.domain.enums import Difficulty, QuestionKind, QuestionStatus, QuizKind

#: The one embedding dimension (ADR-0097). Taken from frog's constant rather than a
#: setting because that constant is what this column was created with: a configurable
#: that disagreed with it could only ever produce vectors the database refuses.
_EMBEDDING_DIM = EMBEDDING_DIM


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
        #: See `Card.__table_args__` for why this is in the database (ADR-0097).
        CheckConstraint(
            "(embedding IS NULL) = (embedding_model IS NULL)",
            name="embedding_names_its_model",
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

    #: Which model produced `embedding`. Task 0039 is what its absence costs: `.env` named
    #: an embedder nothing read, every vector was `HashEmbedder` output, and no query,
    #: log line or test could tell — a column holding two incomparable kinds of vector
    #: is worse than a column holding either, and nothing raises. The stamp is how a
    #: future model change stays a fact rather than a guess.
    embedding_model: Mapped[str | None] = mapped_column(String(120))
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
    """A unit of work the worker claims and runs (ADR-0026, ADR-0073).

    Two kinds (ADR-0076):

    - `kind='generate'` (default) -- run the one-shot pipeline for one
      already-existing `topic_id` (minted by `match_and_create_topics`,
      ADR-0025 -- a job's topic always exists before the job does). A topic
      only ever needs ONE such job in its lifetime, so it is coalesced on
      `topic_id`.
    - `kind='repair'` -- fix or remake a single reported `card_id` (ADR-0076).
      Coalesced on `card_id`, so a topic can have any number of repairs in
      flight for different cards while still holding at most one generate job.
    """

    __tablename__ = "generation_job"
    __table_args__ = (
        # Coalescing lock for generate jobs: at most one outstanding per topic,
        # completed history retained.
        Index(
            "uq_generation_job_topic_pending",
            "topic_id",
            unique=True,
            postgresql_where=text("kind = 'generate' AND status IN ('pending', 'running')"),
        ),
        # Coalescing lock for repair jobs: at most one outstanding per card.
        Index(
            "uq_generation_job_card_pending",
            "card_id",
            unique=True,
            postgresql_where=text("kind = 'repair' AND status IN ('pending', 'running')"),
        ),
        Index("ix_generation_job_status_priority", "status", "priority"),
    )

    #: 'generate' | 'repair' (ADR-0076). A plain string, like `status` -- the
    #: value set is small and the worker branches on it, not the database.
    kind: Mapped[str] = mapped_column(String(16), default="generate", nullable=False)

    topic_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("topic.id", ondelete="CASCADE"), nullable=False
    )
    #: Set only for `kind='repair'` -- the card being fixed or remade. Null for
    #: generate jobs.
    card_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("card.id", ondelete="CASCADE")
    )

    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    #: Live progress for the request-a-topic streaming UI (docs/adr, generation
    #: progress). Written incrementally by generation/pipeline.py as curriculum,
    #: cards, and questions land -- shape is `{"stage", "topic_name",
    #: "subtopics": [{"subtopic_id", "group_title", "difficulty", "cards_target",
    #: "cards_done", "questions_target", "questions_done"}, ...]}`. Null until
    #: the worker actually picks the job up. Best-effort only -- a missing or
    #: stale value never blocks generation itself, only degrades the UI to a
    #: coarser "still working" state.
    progress: Mapped[dict[str, object] | None] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=True
    )
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
    """The one durable piece of the quota system (ADR-0084): today's request
    count per `(key, model)` cell.

    The load balancer keeps the count in memory during a run; this table exists
    so the count survives across the many passes a day contains -- seeded once
    when a balancer is built, written back best-effort as it climbs. The old
    `exhausted_at` / `cooldown_until` columns are gone: "exhausted" is just
    `requests_spent >= rpd`, and a cooldown is a 60-second in-memory fact the
    balancer never re-reads.
    """

    __tablename__ = "quota_ledger"

    day: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    #: `"gemini:{key_index}:{model}"` -- one row per cell per day.
    backend: Mapped[str] = mapped_column(String(64), primary_key=True)
    requests_spent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
