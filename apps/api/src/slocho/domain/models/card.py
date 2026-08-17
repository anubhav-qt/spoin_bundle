"""The card.

content-model.md calls this the highest-leverage schema in the project: the
generation prompt, quality gate, dedup logic, ranker features, chat context and UI
all inherit its shape. Change it deliberately.
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
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from slocho.core.config import get_settings
from slocho.domain.base import Base, CreatedAt, UUIDPrimaryKey, pg_enum
from slocho.domain.enums import CardSource, CardStatus, Difficulty
from slocho.domain.models.topic import Subtopic

_EMBEDDING_DIM = get_settings().embedding_dim


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
