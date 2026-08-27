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
    """A unit of generation work: run the one-shot pipeline (ADR-0026) for one
    already-existing `topic_id` (minted by `match_and_create_topics`,
    ADR-0025 -- a job's topic always exists before the job does).

    The uniqueness key is `topic_id`. A topic only ever needs ONE generation
    job in its lifetime (there is no recurring refill to coalesce, per
    ADR-0026) -- this just collapses concurrent duplicate triggers for the
    same topic into one row, the same way the old subtopic-keyed lock did for
    the demand-driven refill model it replaced.
    """

    __tablename__ = "generation_job"
    __table_args__ = (
        # The coalescing lock. Partial-unique on the pending states, so one
        # topic can have at most one outstanding job while completed history is
        # retained.
        Index(
            "uq_generation_job_topic_pending",
            "topic_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'running')"),
        ),
        Index("ix_generation_job_status_priority", "status", "priority"),
    )

    topic_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("topic.id", ondelete="CASCADE"), nullable=False
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
    #: Set by `QuotaGovernor.mark_rate_limited` when the provider returns a
    #: per-MINUTE 429 for this cell -- `acquire()` skips the cell until it
    #: passes, without spending `requests_spent` (ADR-0058). Shared rather than
    #: in-memory so a throttle one process discovers is not re-discovered by
    #: every other process that then routes straight into the same wall.
    #: Wall-clock, unlike the monotonic value this replaced: it has to be
    #: comparable across processes and hosts.
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class QuotaRequest(Base, UUIDPrimaryKey):
    """One request against a `(key, model)` cell, inside the trailing per-minute
    window (ADR-0058).

    The RPM counterpart to `QuotaLedger`'s daily count, and shared for the same
    reason the ledger is: an in-memory window lets two processes each permit the
    full ceiling, so the provider sees double what either believes it sent.

    **Rows are disposable.** They matter for 60 seconds and are pruned after;
    nothing reads this table for history. That is also why it is a plain row per
    request rather than a counter -- a sliding window needs the individual
    timestamps, and counting rows makes the reserve atomic in one statement
    (see `quota.py`'s `_try_reserve_rpm`) instead of needing a read-modify-write
    under a row lock.
    """

    __tablename__ = "quota_request"

    #: Same `"gemini:{key_index}:{model}"` convention as `QuotaLedger.backend`,
    #: deliberately: the two tables describe the same cell on two time horizons.
    backend: Mapped[str] = mapped_column(String(64), nullable=False)
    #: When the request actually went to the provider. Written at reservation
    #: time and moved forward when the call really fires (`note_request_sent`) --
    #: see `_RpmSlot`'s successor in quota.py for why the window has to be
    #: anchored to the send rather than the grant.
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: False while the cell is granted but the request hasn't left yet. Reserved
    #: rows count toward the ceiling exactly like sent ones -- otherwise
    #: concurrent callers all see room and pile onto the same cell.
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        #: Every query here is "this cell, this last minute", and the prune is
        #: "anything older than that" -- one composite index serves both.
        Index("ix_quota_request_backend_sent_at", "backend", "sent_at"),
    )


class ModelUnavailable(Base, Timestamps):
    """A model the provider has stopped answering on, parked out of rotation
    while a recovery probe checks whether it has come back (ADR-0065).

    Keyed on the MODEL alone, not on a `(key, model)` cell and not on a pool: a
    503 overload or a 504 stall is a property of the model at the provider, so
    one process discovering it should keep every other process -- and both
    ladders that happen to list it -- from walking into the same wall. That is
    the same reasoning that moved the RPM window into the database (ADR-0058);
    this row is the availability counterpart to `QuotaLedger.cooldown_until`.

    Unlike `quota_request`, rows here are few and long-lived enough to be worth
    reading on every `acquire()`; unlike `quota_ledger`, they are not a day's
    accounting and carry no history -- `include_model` deletes the row outright
    the moment a probe gets an answer.
    """

    __tablename__ = "model_unavailable"

    model: Mapped[str] = mapped_column(String(64), primary_key=True)
    #: When this model was last observed unavailable. Rewritten on every
    #: re-exclusion, so it reads as "still failing as of", not "first failed at".
    excluded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: When this exclusion stops being believed, absent a probe clearing it
    #: first. Derived from the probe's own budget, NOT an independent tuning
    #: knob: the probe that owns this row is given a fixed window to reach a
    #: verdict, so an exclusion outliving that window is evidence the prober
    #: died (a short-lived worker pass exiting mid-probe -- see
    #: `_probe_model`'s docstring), not evidence the model is still down.
    #: Without it, one crashed process could park a model for every other
    #: process indefinitely.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: The provider error that caused the exclusion, verbatim-ish. Read by
    #: humans out of a terminal, and by `AllModelsUnavailableError` when it has
    #: to explain that a run stopped on an outage rather than on quota.
    reason: Mapped[str] = mapped_column(String(256), nullable=False)
