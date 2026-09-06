"""The card.

content-model.md calls this the highest-leverage schema in the project: the
generation prompt, quality gate, dedup logic, ranker features, chat context and UI
all inherit its shape. Change it deliberately.
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
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from spoin.domain.base import Base, CreatedAt, Timestamps, UUIDPrimaryKey, pg_enum
from spoin.domain.enums import (
    CardReportReason,
    CardSource,
    CardStatus,
    Difficulty,
    RejectionStage,
    RepairMode,
    RepairStatus,
    VisualKind,
)
from spoin.domain.models.topic import Subtopic

#: The one embedding dimension (ADR-0097). Taken from frog's constant rather than a
#: setting because that constant is what this column was created with: a configurable
#: that disagreed with it could only ever produce vectors the database refuses.
_EMBEDDING_DIM = EMBEDDING_DIM


class Card(Base, UUIDPrimaryKey, CreatedAt):
    __tablename__ = "card"
    __table_args__ = (
        # The feed's candidate query. Everything it filters on, in one index.
        Index("ix_card_subtopic_id_status_difficulty", "subtopic_id", "status", "difficulty"),
        Index("ix_card_topic_id_status_difficulty", "topic_id", "status", "difficulty"),
        # Exactly one active row per family. A partial unique index, so the
        # database enforces it rather than application discipline — the ranking
        # signal depends on this holding.
        Index(
            "uq_card_family_id_active",
            "family_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        UniqueConstraint("family_id", "version"),
        #: GIN, because the question this column exists to answer is a CONTAINMENT
        #: one -- "which cards did this chunk ground?" (rag-design-space 3.12) -- and
        #: a btree cannot answer it. ADR-0089 rejected free-text provenance for
        #: exactly this: a citation nothing can query is not a citation.
        Index(
            "ix_card_grounded_chunk_ids",
            "grounded_chunk_ids",
            postgresql_using="gin",
        ),
        #: A vector that cannot name its model is a vector nobody can safely trust
        #: later, and task 0039 is what that costs: a column silently holding two
        #: incomparable kinds, every comparison across them noise, nothing raising.
        #: In the database rather than in the nine call sites that write one, per
        #: CLAUDE.md -- a rule enforced only by discipline is a wish (ADR-0097).
        CheckConstraint(
            "(content_embedding IS NULL) = (embedding_model IS NULL)",
            name="embedding_names_its_model",
        ),
        #: A visual asset must always state its kind, and kind without an asset
        #: is meaningless (task 0040 Phase 3).
        CheckConstraint(
            "(visual_id IS NULL) = (visual_kind IS NULL)",
            name="visual_kind_accompanies_visual_id",
        ),
    )

    #: Groups every version of the same card. Improving the prompt and
    #: regenerating produces a NEW ROW, not an update — engagement data attaches
    #: to a specific card id, so overwriting v1's row would silently
    #: re-attribute every like and save collected against v1's text to different
    #: content, quietly corrupting the ranking signal the whole personalization
    #: layer depends on.
    family_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    #: System-owned. The generator never sets this — a card is `draft` until the
    #: quality gate passes it, and it never reaches the corpus otherwise.
    status: Mapped[CardStatus] = mapped_column(
        pg_enum(CardStatus, "card_status"),
        default=CardStatus.DRAFT,
        nullable=False,
    )

    topic_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("topic.id", ondelete="CASCADE"), nullable=False
    )
    subtopic_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("subtopic.id", ondelete="CASCADE"), nullable=False
    )

    #: Requested at generation time, then **independently verified** by the batch
    #: judge. A card tagged `beginner` because that is what was asked validates
    #: nothing; only a rating made without knowledge of the request can disagree,
    #: and disagreement is the entire point of a gate.
    difficulty: Mapped[Difficulty] = mapped_column(
        pg_enum(Difficulty, "difficulty"),
        nullable=False,
    )
    #: The judge's independent rating, kept alongside rather than overwriting the
    #: requested one so disagreements stay visible and auditable.
    judged_difficulty: Mapped[Difficulty | None] = mapped_column(pg_enum(Difficulty, "difficulty"))

    title: Mapped[str] = mapped_column(String(120), nullable=False)
    #: The literal, descriptive name of the concept. Always present, never playful —
    #: `title` is what the feed face shows and is playful some of the time, but every
    #: other consumer (quiz stems, remediation links, progress/coverage lists, search,
    #: and the generation prompt's already-covered list) reads THIS field
    #: (ADR-0022). Neither title feeds `content_embedding` — that stays derived from
    #: `body` alone.
    canonical_title: Mapped[str] = mapped_column(String(160), nullable=False)
    #: A purpose-written hook, NOT a truncation of body. It costs nothing — one
    #: more field in the same structured output on the same request, and the free
    #: tier meters requests, not tokens (ADR-0005). The opening of a good
    #: explanation is usually throat-clearing, and the line that stops a scroll is
    #: a different job from the line that opens an essay.
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    #: Markdown. Scrolls inside the expanded card.
    body: Mapped[str] = mapped_column(Text, nullable=False)

    source: Mapped[CardSource] = mapped_column(
        pg_enum(CardSource, "card_source"),
        default=CardSource.GENERATED,
        nullable=False,
    )
    #: Null for generated cards. The column exists now because adding it later
    #: means a data migration, and user-authored cards are a planned direction.
    #: Cost today: two columns, no UI.
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )

    #: Derived locally post-generation (hard rule 5). A DIFFERENT embedding from
    #: the topic embedding used for canonicalization: same technique, different
    #: vectors, different thresholds. Calibrate separately.
    content_embedding: Mapped[list[float] | None] = mapped_column(Vector(_EMBEDDING_DIM))

    #: Which model produced `content_embedding`. Task 0039 is what its absence costs: `.env` named
    #: an embedder nothing read, every vector was `HashEmbedder` output, and no query,
    #: log line or test could tell — a column holding two incomparable kinds of vector
    #: is worse than a column holding either, and nothing raises. The stamp is how a
    #: future model change stays a fact rather than a guess.
    embedding_model: Mapped[str | None] = mapped_column(String(120))

    #: The `chunk.id`s in `the_spoin_universe` whose text was in this card's prompt
    #: (ADR-0089). A real column and not a `gen_meta` key: the question it answers is
    #: "which cards did this retracted chunk ground?", and JSONB containment over
    #: every card is not the shape of that question.
    #:
    #: NULL and `[]` are different facts, deliberately. NULL means the card predates
    #: grounding or was written by a path that does not retrieve; `[]` means retrieval
    #: RAN and had nothing to give -- an empty corpus, or a subtopic it does not
    #: cover. Reading the second as the first would hide exactly the gap the
    #: corpus-authoring track needs to see.
    #:
    #: There is no foreign key, and cannot be: `chunk` lives in a different DATABASE
    #: (ADR-0088). So a dangling id is possible -- a chunk revised out of existence
    #: leaves the card citing something gone, and what that means is an open question
    #: ADR-0089 names rather than answers.
    grounded_chunk_ids: Mapped[list[uuid.UUID] | None] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=True
    )

    #: model, prompt_version, generated_at, batch_id, backend. The backend field is
    #: what makes local-vs-cloud quality measurable and lets a bad batch be traced
    #: and retired (ADR-0008).
    gen_meta: Mapped[dict[str, object]] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), default=dict, nullable=False
    )

    #: Content shapes present in `body` — "code", "diagram", "comparison", any
    #: subset, `[]` for plain prose (ADR-0017). Derived deterministically from
    #: `body` itself (content/archetype.py), never LLM-self-reported — see that
    #: module's docstring for why. A rendering hint, not a business rule: the
    #: web client uses it to pick a collapsed-state preview shape.
    archetype: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)

    #: At most one TRUE per subtopic (not enforced by a DB constraint yet —
    #: today's only writer is the fixture seeder, which maintains it by
    #: construction; a real content-planning step will need to own this
    #: invariant once generation exists). Replaces the old frontend "first
    #: card in this feed station" heuristic, which wasn't even really "one
    #: per subtopic" — a mixed-feed station groups by TOPIC, which can span
    #: several subtopics. See ADR-0017 and docs/tasks/0006.
    is_hero: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    #: Key into the ASCII scene catalog (ADR-0021). Null until the catalog exists —
    #: the generator SELECTS a scene, it never draws one, so this column is meaningless
    #: without a catalog to select from. Kept nullable and populated by nothing today
    #: on purpose: adding it later would mean a data migration and regenerating the
    #: corpus to backfill it (the "do the schema half now" reasoning in CLAUDE.md).
    visual_id: Mapped[str | None] = mapped_column(String(64))
    #: The kind of visual asset attached to the card (task 0040 Phase 3).
    #: Stored explicitly rather than inferred from visual_id's string format.
    visual_kind: Mapped[VisualKind | None] = mapped_column(
        Enum(VisualKind, name="visual_kind", values_callable=lambda e: [m.value for m in e]),
        nullable=True,
    )
    #: {slot_name: text} for the scene named by `visual_id`. Null together with it.
    visual_slots: Mapped[dict[str, str] | None] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite")
    )

    subtopic: Mapped[Subtopic] = relationship(back_populates="cards")
    stats: Mapped[CardStats | None] = relationship(
        back_populates="card", uselist=False, cascade="all, delete-orphan"
    )


class CardStats(Base, CreatedAt):
    """Derived aggregate, rebuildable from the event log (ADR-0011).

    Maintained by a batch job and read directly by the feed. No COUNT(*) over
    engagement in a user-facing request, ever — that is the single most important
    performance decision in the read path, and it is why Redis is not needed in v1.
    """

    __tablename__ = "card_stats"

    card_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("card.id", ondelete="CASCADE"), primary_key=True
    )

    impressions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expands: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    likes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    bookmarks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    explicit_completes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    dwell_completes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skips: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    avg_dwell_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    #: A RATE, never a count. Raw counts make old cards permanently dominant and
    #: new cards permanently invisible, which combined with ranking produces a
    #: cold-start death spiral. This is why impressions must be logged despite
    #: being the highest-volume event: without a denominator there is no rate.
    quality: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    recomputed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    card: Mapped[Card] = relationship(back_populates="stats")


class RejectedCard(Base, UUIDPrimaryKey, CreatedAt):
    """A draft that never became a `Card` row (ADR-0030).

    Kept, not discarded. Every draft that reaches the gate becomes exactly one of:
    an ACTIVE `Card`, or a row here -- never silently dropped. The gate is
    judgment, not proof, so a rejected draft plus the specific reason it failed
    is a labeled example, potentially useful later for evaluating gate accuracy
    or the generator itself -- a plain log line would throw that away for free.

    `title`/`canonical_title`/`summary`/`body` here are the content AT THE TIME
    OF REJECTION -- post pass-1-correction for both near-duplicate and
    verification rejects, since correction runs first (ADR-0030).
    """

    __tablename__ = "rejected_card"
    __table_args__ = (Index("ix_rejected_card_subtopic_id", "subtopic_id"),)

    topic_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("topic.id", ondelete="CASCADE"), nullable=False
    )
    subtopic_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("subtopic.id", ondelete="CASCADE"), nullable=False
    )
    #: What was ASKED for -- there is no independently-judged difficulty to
    #: store alongside it, unlike `Card.judged_difficulty`, since a rejected
    #: draft never reached a confirmed verdict.
    requested_difficulty: Mapped[Difficulty] = mapped_column(
        pg_enum(Difficulty, "difficulty"), nullable=False
    )

    title: Mapped[str] = mapped_column(String(120), nullable=False)
    canonical_title: Mapped[str] = mapped_column(String(160), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)

    #: Where in the gate this draft was thrown out -- a `GROUP BY`, not string
    #: parsing on `reason`.
    stage: Mapped[RejectionStage] = mapped_column(
        pg_enum(RejectionStage, "rejection_stage"), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)

    #: Same shape as `Card.gen_meta` -- backend, generated_at, batch_id.
    gen_meta: Mapped[dict[str, object]] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), default=dict, nullable=False
    )


class CardReport(Base, UUIDPrimaryKey, CreatedAt):
    """A reader flagging a live card as structurally broken (ADR-0076).

    Unique per `(card_id, user_id)` -- one account reports a given card at most
    once; a repeat report updates the existing row. Not an `EngagementEvent`: a
    report is a moderation signal with its own lifecycle, never a ranking input.
    """

    __tablename__ = "card_report"
    __table_args__ = (
        UniqueConstraint("card_id", "user_id", name="uq_card_report_card_user"),
        Index("ix_card_report_unresolved", "card_id", postgresql_where=text("resolved_at IS NULL")),
    )

    card_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("card.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    reason: Mapped[CardReportReason] = mapped_column(
        pg_enum(CardReportReason, "card_report_reason"), nullable=False
    )
    #: The reader's own words on what looks wrong. Optional -- the reason enum
    #: is the required part.
    note: Mapped[str | None] = mapped_column(Text)
    #: Set when the operator has acted on this card (delete / fix / remake), so
    #: the admin queue query is `WHERE resolved_at IS NULL` -- reports for one
    #: card are resolved together, by card, not individually.
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CardRepair(Base, UUIDPrimaryKey, Timestamps):
    """The operator's instruction for a reported card, plus the audit trail
    (ADR-0076). One row per repair attempt; `job` tracks its execution.

    `mode=FIX`  -- `ContentGenerator.repair_card_structure` rewrites the visual/
                   structural slots from the rendered image + `guidance`;
                   structural checks only, then a new family version.
    `mode=REMAKE` -- regenerate from `guidance` (required here) through the full
                   quality gate, then a new family version.
    """

    __tablename__ = "card_repair"
    __table_args__ = (Index("ix_card_repair_status", "status"),)

    card_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("card.id", ondelete="CASCADE"), nullable=False
    )
    #: The `generation_job` row (`kind='repair'`) that runs this. Nullable only
    #: for the instant between creating the repair and enqueuing the job.
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("generation_job.id", ondelete="SET NULL")
    )
    mode: Mapped[RepairMode] = mapped_column(pg_enum(RepairMode, "repair_mode"), nullable=False)
    #: Operator free text. Optional for FIX (steer the structural repair),
    #: REQUIRED for REMAKE (the brief for the new card) -- enforced at the API,
    #: not the column.
    guidance: Mapped[str | None] = mapped_column(Text)
    #: The card rendered to PNG by the admin page (same `html-to-image` call as
    #: the share button), sent to the FIX repair call as the visual reference.
    #: Deferred like `User.avatar_image` -- a 2x card screenshot is well under a
    #: megabyte, read once by the worker, never on a hot path. Null for REMAKE.
    source_image: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    status: Mapped[RepairStatus] = mapped_column(
        pg_enum(RepairStatus, "repair_status"), default=RepairStatus.PENDING, nullable=False
    )
    #: The new `card` row this repair produced, once it has one.
    result_card_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("card.id", ondelete="SET NULL")
    )
    #: Why a FAILED repair failed -- a structural check that didn't pass, a
    #: gate rejection, or a call that never returned. Surfaced on the admin page.
    error: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Set when the operator dismisses a DONE/FAILED repair from the admin
    #: before/after view (ADR-0076). A resolved repair stays on the page --
    #: showing the new card with a before/after toggle -- until this is set.
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AskConversation(Base, UUIDPrimaryKey, Timestamps):
    """One persistent AskAI thread, scoped to a topic (ADR-0077, revised).

    Partial-unique on `(user_id, topic_id) WHERE status = 'active'`: at most one
    live thread per topic per user. "Start over" archives the active one and a
    fresh row is opened on the next question.
    """

    __tablename__ = "ask_conversation"
    __table_args__ = (
        Index(
            "uq_ask_conversation_active",
            "user_id",
            "topic_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    topic_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("topic.id", ondelete="CASCADE"), nullable=False
    )
    #: 'active' | 'archived'. A plain string like `generation_job.status` -- a
    #: two-value set the app branches on, not worth a PG enum + migration.
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AskMessage(Base, UUIDPrimaryKey, CreatedAt):
    """One turn in an `ask_conversation` (ADR-0077, revised)."""

    __tablename__ = "ask_message"
    __table_args__ = (Index("ix_ask_message_conversation", "conversation_id", "created_at"),)

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("ask_conversation.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: 'user' | 'assistant'. Plain string, same reasoning as
    #: `AskConversation.status`.
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    #: Only meaningful on an `assistant` row: `false` when the turn was refused
    #: (embedding gate or `OFF_TOPIC` sentinel). `content` then holds the
    #: server-built hint, never the model's prose.
    on_topic: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class AskUsage(Base):
    """One row per user per UTC day, counting AskAI assistant turns that reached
    the provider (ADR-0077). A plain counter, deliberately NOT the quota
    governor: the governor rations a shared provider budget, this rations one
    user against everyone else. Gate refusals and errors cost nothing and are
    not counted here.
    """

    __tablename__ = "ask_usage"

    #: UTC day start -- matches `quota_ledger`'s day boundary, not ADR-0062's
    #: reader-local day (that is a goal-ring display choice, not a rate limit).
    day: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    questions_spent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
