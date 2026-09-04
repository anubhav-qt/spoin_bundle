"""The corpus store: `document` and `chunk`.

Shape and reasoning: docs/adr/0088-the-spoin-universe.md. Field comments here record
provenance and the constraint behind a column, per CLAUDE.md's "why, never what" rule;
`spoin/domain/models/card.py` is the canonical example of the style.

**Phase 1 is an empty, migrated store.** No ingestion and no retrieval live here yet —
those are task 0038's Phases 2 and 3. What this file owes the corpus-authoring track
is a schema stable enough to author against before the corpus arrives.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from frog.universe.base import Base, CreatedAt, UUIDPrimaryKey

#: ADR-0087: the same 384 dimensions and the same `BAAI/bge-small-en-v1.5` model as
#: `card.content_embedding` in `spoin_db_2`. This is load-bearing, not a default —
#: corpus vectors and card vectors that are not in the same space cannot be compared,
#: and nothing would raise if they diverged.
EMBEDDING_DIM = 384


class DocumentKind(StrEnum):
    """The two content kinds, which retrieval does not treat interchangeably.

    `SPOIN_CANON` — how the product itself works: dual titles (ADR-0022), archetypes
    (ADR-0017), quiz-gated progression (ADR-0009), the ASCII box rule, CLAUDE.md's
    silliness-in-the-hook-layer rule. Relevant to nearly every generation call
    regardless of subject, because a small model does not know our conventions.

    `TOPIC_SOURCE` — curated authoritative material, relevant by subject.

    A real Postgres enum rather than a free-text column (ADR-0088): a typo in a
    document's front matter would otherwise create a silent third kind that nothing
    ever retrieves.
    """

    SPOIN_CANON = "spoin_canon"
    TOPIC_SOURCE = "topic_source"


class Document(Base, UUIDPrimaryKey, CreatedAt):
    """One authored source file, and enough provenance to cite it.

    Provenance is not optional. "We can back with grounding why our material is high
    quality" is a claim about *citability*, so the citation has to be storable —
    ADR-0089's whole argument for recording chunk IDs on a card dead-ends here if a
    chunk cannot say where it came from.
    """

    __tablename__ = "document"

    #: Where the material came from — a URL, or an origin description for material
    #: distilled from our own ADRs. NOT NULL: a document nothing can cite is not a
    #: document this corpus wants.
    source: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)

    kind: Mapped[DocumentKind] = mapped_column(
        Enum(
            DocumentKind,
            name="document_kind",
            values_callable=lambda e: [member.value for member in e],
        ),
        nullable=False,
    )

    #: Path within the delivered corpus, and the document's *identity*. Unique, so
    #: re-ingesting a revised file updates one row rather than accumulating rows.
    source_path: Mapped[str] = mapped_column(String(1000), nullable=False, unique=True)

    #: sha256 of the raw file. This is what makes re-ingestion idempotent (ADR-0088):
    #: unchanged hash, skip; changed hash, replace this document's chunks in one
    #: transaction. Chosen over a hand-maintained version field in front matter
    #: because a version bump can be forgotten and its failure mode is stale chunks
    #: silently surviving a revision — a hash cannot be forgotten.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    #: When the SOURCE MATERIAL is from — deliberately distinct from `ingested_at`
    #: below. A card citing a source that has since gone stale needs the former to
    #: say so; the latter only records when we happened to read it. Nullable: Spoin
    #: canon distilled from our own docs has no meaningful source date.
    source_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    #: When we read it. Set by ingestion, not by the database, so a re-ingestion that
    #: finds an unchanged hash can leave it alone.
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    chunks: Mapped[list[Chunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )


class Chunk(Base, UUIDPrimaryKey, CreatedAt):
    """A retrievable span of one document."""

    __tablename__ = "chunk"

    #: CASCADE because a document's chunks have no meaning without it, and because
    #: re-ingesting a changed document deletes and rebuilds them wholesale.
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document.id", ondelete="CASCADE"), nullable=False
    )

    #: Position within the document. Makes a chunk citable as "part 3 of", and gives
    #: retrieval a way to widen a hit to its neighbours later without guessing.
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)

    text: Mapped[str] = mapped_column(Text, nullable=False)

    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)

    #: Normalized topic slugs, produced by `spoin.embeddings.normalize_topic_text` at
    #: ingestion time. `the_spoin_universe` is a SEPARATE database, so a chunk cannot
    #: hold a foreign key to `spoin_db_2`'s `topic` table — tagging crosses that
    #: boundary by value (ADR-0088). Sharing one normalizer is what stops tags and
    #: canonical topic names becoming two vocabularies.
    #:
    #: On `chunk` rather than `document` so a broad authoritative source can have
    #: differently-tagged sections. A filter that is available and NOT applied by
    #: default: retrieval is cross-topic (ADR-0088).
    topic_tags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")

    document: Mapped[Document] = relationship(back_populates="chunks")

    __table_args__ = (
        #: Ingestion writes chunks in order and retrieval cites them by position;
        #: both want one document's chunks together.
        Index("ix_chunk_document_id_ordinal", "document_id", "ordinal", unique=True),
        #: GIN because `topic_tags` is an array searched with containment operators.
        #: Present even though the filter is off by default — Phase 3 inspects
        #: cross-topic retrieval scores, and turning the filter on should not then
        #: require a migration to be usable.
        Index("ix_chunk_topic_tags", "topic_tags", postgresql_using="gin"),
    )
