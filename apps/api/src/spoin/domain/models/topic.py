"""Users, topics and the curriculum.

The pattern to internalise here is ADR-0004's **shared entity, personal label**:

    topic         canonical entity — owns the corpus and the embedding
    topic_alias   raw strings mapping onto a canonical topic ("k8s" -> kubernetes)
    user_topic    (user_id, topic_id, display_name) — what THIS user calls it

One user sees "k8s", another sees "Kubernetes", both read the same cards. This
recurs elsewhere in the system; name it when you see it.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from frog.universe.models import EMBEDDING_DIM
from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from spoin.domain.base import Base, CreatedAt, Timestamps, UUIDPrimaryKey, pg_enum
from spoin.domain.enums import Difficulty, TopicEdgeKind

if TYPE_CHECKING:
    from spoin.domain.models.card import Card

#: The one embedding dimension (ADR-0097). Taken from frog's constant rather than a
#: setting because that constant is what this column was created with: a configurable
#: that disagreed with it could only ever produce vectors the database refuses.
_EMBEDDING_DIM = EMBEDDING_DIM


class User(Base, UUIDPrimaryKey, Timestamps):
    __tablename__ = "app_user"  # "user" is reserved in Postgres

    #: Nullable so a guest can hold a row with no email at all (see
    #: `auth/rate_limit.py`'s neighbour `api/routers/auth.py` for the guest
    #: flow). Postgres treats every NULL as distinct under a UNIQUE constraint,
    #: so many guests can coexist with `email IS NULL` without collision.
    email: Mapped[str | None] = mapped_column(String(320), unique=True, nullable=True)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    google_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    #: Gates onboarding, not signup — set once the onboarding flow finishes.
    onboarding_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gender: Mapped[str | None] = mapped_column(String(32), nullable=True)
    avatar_icon: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: Deferred: without this, EVERY `session.get(User, ...)` — including
    #: `/auth/me`, which the web client calls on every navigation — pulls up to
    #: 5MB of image bytes off the wire to answer questions that never look at
    #: them. The one endpoint that serves the bytes loads them explicitly with
    #: `undefer`; `has_avatar_image` is answered by the column below instead of
    #: by testing this one for None, so the common path never triggers a lazy
    #: load either.
    avatar_image: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True, deferred=True)
    #: Denormalized so "does this user have a photo?" is answerable without
    #: touching the blob. Written only alongside `avatar_image`, by
    #: ProfileService — the two are never set independently.
    has_avatar_image: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    #: Sniffed from the uploaded bytes at upload time (profile/images.py), not
    #: taken from the request. The download endpoint previously answered every
    #: avatar as `image/jpeg` regardless of what was actually stored.
    avatar_media_type: Mapped[str | None] = mapped_column(String(32), nullable=True)

    #: How many cards a day this user is aiming for. A target the profile's
    #: activity figures are read against -- deliberately NOT an input to feed
    #: selection, which stays governed by per-topic progression and the
    #: server-side DIFFICULTY_MIX (ADR-0010). NOT NULL with a server default so
    #: every existing row gets the same starting target as a new one, and no
    #: read path has to handle a null.
    daily_card_goal: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10, server_default="10"
    )

    topics: Mapped[list[UserTopic]] = relationship(back_populates="user")

    @property
    def is_guest(self) -> bool:
        """A guest is a `User` row with no login method attached yet — no
        password, no linked Google account, and (the field this actually
        keys off) no email. Claiming an account sets `email`, which is why
        this is derived rather than a separate stored flag: it can't drift
        out of sync with the fields that actually gate login."""
        return self.email is None


class Topic(Base, UUIDPrimaryKey, Timestamps):
    """The canonical entity. Content is generated once per topic and shared."""

    __tablename__ = "topic"

    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    #: The system's name for the topic. Never rendered — the UI always shows
    #: `user_topic.display_name`.
    canonical_name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    embedding: Mapped[list[float] | None] = mapped_column(Vector(_EMBEDDING_DIM))

    #: Which model produced `embedding`. Task 0039 is what its absence costs: `.env` named
    #: an embedder nothing read, every vector was `HashEmbedder` output, and no query,
    #: log line or test could tell — a column holding two incomparable kinds of vector
    #: is worse than a column holding either, and nothing raises. The stamp is how a
    #: future model change stays a fact rather than a guess.
    embedding_model: Mapped[str | None] = mapped_column(String(120))

    #: Seeded by us versus minted from a user's custom topic. Seeded topics
    #: outrank custom ones in the generation queue (ADR-0003 §6).
    is_seeded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    #: A broad topic ("Mathematics") gets a survey curriculum and emits deep_dive
    #: edges; a narrow one ("Linear Algebra") gets a course. The completion copy
    #: differs and must stay honest about which this is (ADR-0007).
    is_survey: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    #: Deep-dive topics are created immediately but get curricula lazily, on first
    #: subscription. Nothing here is generated until someone wants it.
    curriculum_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    #: Denormalised for the fairness cap and fill priority (ADR-0006). Maintained
    #: by a batch job — never counted at request time.
    subscriber_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    subtopics: Mapped[list[Subtopic]] = relationship(
        back_populates="topic", cascade="all, delete-orphan"
    )
    aliases: Mapped[list[TopicAlias]] = relationship(
        back_populates="topic", cascade="all, delete-orphan"
    )


class TopicAlias(Base, UUIDPrimaryKey, CreatedAt):
    """Every raw string a user has typed, and where it resolved to.

    The LLM judge's verdict for a mid-band pair is cached here **permanently** —
    that pair is never paid for again (ADR-0004).

    Merges are reversible by construction: the mapping is data. When we discover a
    bad merge, and we will, the fix is repointing an alias rather than archaeology
    on user records.
    """

    __tablename__ = "topic_alias"
    __table_args__ = (UniqueConstraint("normalized_text", name="uq_topic_alias_normalized_text"),)

    #: Post-normalization. Whatever normalization task 0001 settles on must be
    #: applied identically here and at match time, or the cache silently misses.
    normalized_text: Mapped[str] = mapped_column(String(200), nullable=False)
    raw_text: Mapped[str] = mapped_column(String(200), nullable=False)

    topic_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("topic.id", ondelete="CASCADE"), nullable=False
    )
    #: 'llm_batch_match' as of ADR-0025 (every match decision flows through the
    #: batched LLM call now). Older rows predating that migration may still
    #: carry 'auto_merge' or 'llm_judge' from the threshold-banded system it
    #: replaced. Kept so a bad decision can be audited after the fact.
    decided_by: Mapped[str] = mapped_column(String(20), nullable=False)
    similarity: Mapped[float | None] = mapped_column()

    topic: Mapped[Topic] = relationship(back_populates="aliases")


class UserTopic(Base, UUIDPrimaryKey, Timestamps):
    """A subscription, plus the name this user gave it.

    The three-free-custom-topics limit is enforced on this table, server-side. Note
    the interaction with ADR-0004: a custom topic that canonicalizes onto an
    existing topic still consumes a slot. Users buy slots in their own list, not
    entries in the shared corpus.
    """

    __tablename__ = "user_topic"
    __table_args__ = (UniqueConstraint("user_id", "topic_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    topic_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("topic.id", ondelete="CASCADE"), nullable=False
    )
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: 0-359 hue angle, -1 to opt out of topic color entirely (ADR-0051,
    #: render the plain palette accent instead), or null. Per subscription, not
    #: on `Topic` itself: same shared-entity/personal-label split as
    #: `display_name`, so two users can color the same topic differently.
    #:
    #: ADR-0075 changed how a fresh subscription gets its default. With a real
    #: embedder, `topics/accent_color.assign_accent_hue` picks a hue from a
    #: colour vocabulary by embedding similarity to the topic, distance-filtered
    #: against the user's other topics, and writes that 0-359 value here at
    #: subscribe time. `null` now means "no server-assigned hue" -- a
    #: pre-ADR-0075 row, or one created without a real embedder -- and the client
    #: renders `defaultTopicHue` (ADR-0034's curated-10-then-hash) for it, same
    #: as it always has. No backfill; old rows stay null and render correctly.
    accent_hue: Mapped[int | None] = mapped_column(Integer, nullable=True)

    user: Mapped[User] = relationship(back_populates="topics")
    topic: Mapped[Topic] = relationship()


class TopicEdge(Base, UUIDPrimaryKey, CreatedAt):
    """A flat edge, not a tree (ADR-0007).

    Hierarchy would rebuild the unbounded-nesting problem one level up. Edges are
    for discovery only and carry no curriculum or completion semantics.
    """

    __tablename__ = "topic_edge"
    __table_args__ = (
        UniqueConstraint("from_topic_id", "to_topic_id", "kind"),
        CheckConstraint("from_topic_id <> to_topic_id", name="no_self_edge"),
    )

    from_topic_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("topic.id", ondelete="CASCADE"), nullable=False
    )
    to_topic_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("topic.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[TopicEdgeKind] = mapped_column(
        pg_enum(TopicEdgeKind, "topic_edge_kind"),
        default=TopicEdgeKind.DEEP_DIVE,
        nullable=False,
    )


class Subtopic(Base, UUIDPrimaryKey, CreatedAt):
    """A curriculum slot. Generation targets one of these, never a bare topic.

    That conversion — from the negative constraint "avoid these 200 titles" to the
    positive one "write about pod scheduling" — is the whole point of ADR-0007.
    LLMs are substantially more reliable pointed at a target than avoiding a list.
    """

    __tablename__ = "subtopic"
    __table_args__ = (
        Index("ix_subtopic_topic_id_difficulty", "topic_id", "difficulty"),
        Index("ix_subtopic_group_id", "subtopic_group_id"),
        CheckConstraint("min_cards <= target_cards", name="min_within_target"),
        CheckConstraint("target_cards BETWEEN 5 AND 25", name="target_cards_band"),
    )

    topic_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("topic.id", ondelete="CASCADE"), nullable=False
    )
    #: Groups this subtopic with its siblings at other difficulty tiers — one
    #: shared id per curriculum-authored *concept*, minted once when the curriculum
    #: pass creates the group and reused across however many tiers it decided the
    #: concept needs (1-3; the model is never forced to fill all three). A
    #: standalone subtopic with no tier siblings still gets its own group id, of
    #: size one. This is what makes ADR-0007's "existing titles, across all
    #: difficulties, tagged with their level" answerable — before this field
    #: existed there was no way to tell two Subtopic rows were "the same slot" at
    #: different tiers versus two unrelated subtopics that happened to be created
    #: in the same curriculum pass.
    subtopic_group_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), default=uuid.uuid4, nullable=False
    )
    difficulty: Mapped[Difficulty] = mapped_column(
        pg_enum(Difficulty, "difficulty"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    #: Feeds the generation prompt directly, so it is prose for a model to read,
    #: not a label for a human to skim.
    description: Mapped[str] = mapped_column(Text, nullable=False)

    #: The planner's ideal count: a ceiling and a priority weight.
    target_cards: Mapped[int] = mapped_column(Integer, nullable=False)
    #: The coverage threshold. Completion is defined against **this**, not
    #: target_cards — the planner guesses before generation happens and cannot know
    #: the quality-gate rejection rate, so defining coverage against its
    #: aspirational number leaves users stuck at 94% forever (ADR-0007).
    min_cards: Mapped[int] = mapped_column(Integer, nullable=False)

    #: A curriculum-authoring hint. Cards are standalone and unordered by design,
    #: so this may prove dead weight — see content-model.md's open questions.
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    #: Predetermined capacity / quotas for each card type (prose, code, diagram, comparison, ascii)
    card_type_quotas: Mapped[dict[str, int] | None] = mapped_column(JSONB, nullable=True)

    topic: Mapped[Topic] = relationship(back_populates="subtopics")
    cards: Mapped[list[Card]] = relationship(back_populates="subtopic")
