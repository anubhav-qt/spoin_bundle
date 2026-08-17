"""Engagement: three distinct kinds of data, not one table (ADR-0011).

    1. append-only events   source of truth, immutable, high volume
    2. mutable state        likes, bookmarks, notes, seen-state — can be undone
    3. derived aggregates   caches, always rebuildable from (1)

Merging them makes all three awkward: likes are mutable state and impressions are
immutable facts, with wildly different volumes and lifetimes.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from spoin.domain.base import Base, CreatedAt, Timestamps, UUIDPrimaryKey, pg_enum
from spoin.domain.enums import Difficulty, EngagementKind, SeenState

# ----------------------------------------------------------------------------
# 1. Append-only events
# ----------------------------------------------------------------------------


class EngagementEvent(Base):
    """Immutable, never updated. The truth from which every aggregate is rebuilt.

    This is what makes a smarter ranker possible in two years without having
    thrown the data away.
    """

    __tablename__ = "engagement_event"
    __table_args__ = (
        Index("ix_engagement_event_card_id_kind", "card_id", "kind"),
        Index("ix_engagement_event_user_id_occurred_at", "user_id", "occurred_at"),
        CheckConstraint("dwell_ms IS NULL OR dwell_ms >= 0", name="dwell_non_negative"),
    )

    #: Client-generated, and the primary key precisely so a retry collides instead
    #: of inserting twice. Flaky networks produce duplicates; without this,
    #: impression counts inflate and every rate downstream is wrong.
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    card_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("card.id", ondelete="CASCADE"), nullable=False
    )
    topic_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    subtopic_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)

    kind: Mapped[EngagementKind] = mapped_column(
        pg_enum(EngagementKind, "engagement_kind"), nullable=False
    )
    dwell_ms: Mapped[int | None] = mapped_column(Integer)

    #: SERVER-assigned, always. Client clocks are wrong, and in some cases
    #: deliberately so.
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    #: The client's own timestamp, kept only for ordering within a batch. Never
    #: used as truth.
    client_occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    session_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))


# ----------------------------------------------------------------------------
# 2. Mutable state
# ----------------------------------------------------------------------------


class CardLike(Base, CreatedAt):
    __tablename__ = "card_like"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    card_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("card.id", ondelete="CASCADE"), primary_key=True
    )


class CardBookmark(Base, CreatedAt):
    __tablename__ = "card_bookmark"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    card_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("card.id", ondelete="CASCADE"), primary_key=True
    )


class CardNote(Base, Timestamps):
    """Per-user, per-card, and private. Never shared, never fed to ranking."""

    __tablename__ = "card_note"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    card_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("card.id", ondelete="CASCADE"), primary_key=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)


class UserCardState(Base, Timestamps):
    """Seen-state. The source of truth; `UserSeenBitmap` is derived from it.

    Three states plus a cycle counter (ADR-0010), which is exactly why this is a
    table and not just bits: three states and a counter is not one bit, and a user
    reporting a repeat is one query here versus decoding a bytea there.
    """

    __tablename__ = "user_card_state"
    __table_args__ = (
        Index("ix_user_card_state_user_id_topic_id_state", "user_id", "topic_id", "state"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    card_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("card.id", ondelete="CASCADE"), primary_key=True
    )
    #: Denormalised off the card so the feed's eligibility query does not have to
    #: join back to `card` to scope by topic.
    topic_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    subtopic_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)

    state: Mapped[SeenState] = mapped_column(
        pg_enum(SeenState, "seen_state"), default=SeenState.UNSEEN, nullable=False
    )
    #: The cycle in which this card was deferred. Eligible again once the topic's
    #: current cycle has moved past it — this is the second-chance mechanism that
    #: makes scrolling past cost nothing.
    deferred_cycle: Mapped[int | None] = mapped_column(Integer)
    #: Which path marked it SEEN. Both satisfy the progression gate; they are very
    #: different signals for ranking.
    completed_via: Mapped[EngagementKind | None] = mapped_column(
        pg_enum(EngagementKind, "engagement_kind")
    )
    seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserTopicCycle(Base, Timestamps):
    """The cycle counter, per (user, topic, difficulty).

    Advances when no UNSEEN cards remain at that difficulty across all subtopics,
    which is what releases the DEFERRED pile for a second pass.
    """

    __tablename__ = "user_topic_cycle"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    topic_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("topic.id", ondelete="CASCADE"), primary_key=True
    )
    difficulty: Mapped[Difficulty] = mapped_column(
        pg_enum(Difficulty, "difficulty"), primary_key=True
    )
    cycle: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


# ----------------------------------------------------------------------------
# 3. Derived aggregates — rebuildable, maintained by batch jobs
# ----------------------------------------------------------------------------


class UserTopicAffinity(Base, Timestamps):
    """This user's engagement weight per topic. Drives the interleave plan."""

    __tablename__ = "user_topic_affinity"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    topic_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("topic.id", ondelete="CASCADE"), primary_key=True
    )
    affinity: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    recomputed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserSubtopicProgress(Base, Timestamps):
    """seen_count / total_count — the 80% coverage gate's inputs."""

    __tablename__ = "user_subtopic_progress"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    subtopic_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("subtopic.id", ondelete="CASCADE"), primary_key=True
    )
    seen_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class UserSeenBitmap(Base, Timestamps):
    """Derived read model over `user_card_state` (ADR-0010).

    Removes the feed query's most expensive component (the anti-join), and
    `popcount` gives per-subtopic seen counts for free — which is exactly what the
    80% gate needs.

    **Always rebuildable from the table**, so drift is recoverable rather than
    fatal. A periodic reconciliation job makes it a non-event. This is a
    materialized read model, not a compromise between two options — and it is only
    viable because ADR-0007 bounded the corpus at ~750 cards/topic (~94 bytes).
    """

    __tablename__ = "user_seen_bitmap"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    topic_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("topic.id", ondelete="CASCADE"), primary_key=True
    )
    bits: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    rebuilt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ----------------------------------------------------------------------------
# Feed serving state (ADR-0010)
# ----------------------------------------------------------------------------


class FeedSlate(Base, UUIDPrimaryKey, Timestamps):
    """~25 ranked card ids for ONE topic. Expensive to compute, rarely invalidated.

    Per topic rather than per feed, because `card_quality` is an engagement rate
    and rates are only commensurable *within* a topic. One combined slate would
    force cross-topic normalization that is fiddly and easy to get subtly wrong,
    and would let a "hot" topic dominate every page regardless of affinity.
    """

    __tablename__ = "feed_slate"
    __table_args__ = (UniqueConstraint("user_id", "topic_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    topic_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("topic.id", ondelete="CASCADE"), nullable=False
    )
    #: Ranked card ids, in order.
    card_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(PGUUID(as_uuid=True)), nullable=False)
    #: How far into this slate the user has read. Persists across filter changes,
    #: which is why filtering never causes repeats or skips.
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    #: Whether this slate was built under a starved pool (ADR-0006). Exposed to the
    #: client so the end-of-feed state can be honest rather than an endless spinner.
    degraded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FeedPlan(Base, UUIDPrimaryKey, Timestamps):
    """The interleave plan: [topic_id x 50], affinity-weighted round-robin.

    Cheap, and regenerated freely — on filter change, affinity shift, or slate
    refill. Position is a single integer into it, so pagination stays simple.

    The principle: cache at the layer where invalidation is rare (the slate), and
    keep the volatile layer cheap enough that recomputing it is free.
    """

    __tablename__ = "feed_plan"
    __table_args__ = (UniqueConstraint("user_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    topic_order: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    #: The topic filter this plan was built for; a change regenerates the plan but
    #: leaves every slate intact.
    filter_key: Mapped[str] = mapped_column(String(64), nullable=False, default="")
