"""The curriculum store in `the_spoin_universe`: `curriculum` and `curriculum_subtopic`.

Architecture: `docs/architecture/authored-curriculum.md` §7. A curriculum is teaching
structure, not knowledge, so it lives in its own tables here and **never** in
`document`/`chunk` -- there is deliberately no vector column and nothing embedded,
because syllabus scaffolding in the retrieval pool is something cards would ground on.

The only consumer of these rows is the deterministic projection into `Topic`/`Subtopic`
(task 3). They carry no model output and no judgment -- just the authored file, parsed.

Registered on `frog.universe.base.Base` so they share the one metadata and the one
alembic chain the corpus tables use (`make universe-migrate`).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from frog.universe.base import Base, CreatedAt, UUIDPrimaryKey


class Curriculum(Base, UUIDPrimaryKey, CreatedAt):
    """One authored `curricula/<topic>/curriculum.md`, parsed.

    Idempotency mirrors `document` exactly (ADR-0088): identity is `source_path`,
    change is a sha256 of the raw file, and re-ingesting an unchanged file is a
    no-op.
    """

    __tablename__ = "curriculum"

    #: Path within the curricula tree, POSIX-separated -- `rust/curriculum.md`. The
    #: curriculum's identity; unique so a re-ingested revision updates one row.
    source_path: Mapped[str] = mapped_column(String(1000), nullable=False, unique=True)

    #: sha256 of the raw file, as delivered. Unchanged hash -> skip; changed hash ->
    #: replace this curriculum's subtopics in one transaction.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    #: The canonical topic name, as a learner would say it -- the projection's match
    #: key against `topic.canonical_name` in `spoin_db_2` (crosses the database
    #: boundary by value, like every other cross-DB reference in this project).
    topic_name: Mapped[str] = mapped_column(String(500), nullable=False)

    description: Mapped[str] = mapped_column(Text, nullable=False)

    #: Mirrors `topic.is_survey` in `spoin_db_2` (ADR-0007) by value.
    is_survey: Mapped[bool] = mapped_column(Boolean, nullable=False)

    #: Set by ingestion, not the database, so an unchanged re-ingest leaves it alone
    #: (same as `document.ingested_at`).
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    subtopics: Mapped[list[CurriculumSubtopic]] = relationship(
        back_populates="curriculum",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CurriculumSubtopic.ordinal",
    )


class CurriculumSubtopic(Base, UUIDPrimaryKey, CreatedAt):
    """One curriculum unit. Becomes a subtopic group (one row per tier) in the
    projection."""

    __tablename__ = "curriculum_subtopic"
    __table_args__ = (
        #: Ingestion writes subtopics in file order and the projection reads them
        #: back the same way; the unique pair also stops a re-ingest doubling them.
        Index(
            "ix_curriculum_subtopic_curriculum_id_ordinal",
            "curriculum_id",
            "ordinal",
            unique=True,
        ),
    )

    #: CASCADE because a subtopic has no meaning without its curriculum, and a
    #: revision deletes and rebuilds them wholesale.
    curriculum_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("curriculum.id", ondelete="CASCADE"), nullable=False
    )

    #: Position within the file. `prerequisites` is the real ordering; this is just
    #: for a stable read-back.
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)

    #: Stable -- it is the projection's match key against `subtopic.title`, so
    #: renaming one replaces the subtopic rather than editing it.
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    #: Titles of other subtopics in this same curriculum. A DAG, checked at
    #: `make curriculum-check` before a row is ever written.
    prerequisites: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )

    #: Corpus paths (relative to `docs/the_spoin_universe/corpus/`) that teach this
    #: subtopic. Every path is verified to exist by the validator; the projection
    #: resolves them to `document` ids.
    source_paths: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )

    #: `{tier: {"target_cards": int, "card_types": {type: int}}}` for the 1-3 tiers
    #: this subtopic is taught at. Stored as JSONB rather than a child table
    #: because the only reader is the projection and the shape is already guaranteed
    #: by `make curriculum-check` (`frog.curriculum.contract`): tier keys in
    #: {beginner, intermediate, advanced}, `target_cards` in 5-25, `card_types`
    #: keys a subset of the five and summing to `target_cards`.
    tiers: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    curriculum: Mapped[Curriculum] = relationship(back_populates="subtopics")
