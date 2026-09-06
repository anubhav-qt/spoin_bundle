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
    CheckConstraint,
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

#: ADR-0092: `Qwen/Qwen3-Embedding-0.6B`, 1024 dimensions. Supersedes ADR-0087's
#: 384-dim commitment — comparability with `card.content_embedding` is preserved by
#: both moving together, not by the number staying still.
#:
#: ⚠️ They have NOT both moved yet. `spoin_db_2` stays at 384 until the regeneration
#: wipe, because `spoin.domain.models.topic` declares `Vector(...)` from
#: `embedding_dim` at import time and changing it early would make the ORM disagree
#: with the live schema. The divergence is safe only because nothing currently
#: compares a card vector to a chunk vector, and `spoin_db_2`'s vectors are hash
#: output (task 0039) — meaningless in any space. It ends at the regeneration.
EMBEDDING_DIM = 1024


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


class DocumentScope(StrEnum):
    """Whether a document's subject is a field being toured or a subject being taught.

    Mirrors `topic.is_survey` in `spoin_db_2` (ADR-0007), by value rather than by
    reference — the corpus is a separate database and cannot hold a foreign key to it.

    It is recorded because it changes what the material *is*, not merely where it is
    filed: survey material is breadth (a field's branches and how they relate), topic
    material is depth (one subject to bedrock). Retrieval assembling a survey
    curriculum wants the former; a deep-dive wants the latter, and nothing downstream
    can tell them apart from the prose alone.
    """

    SURVEY = "survey"
    TOPIC = "topic"


class ImageLicence(StrEnum):
    """The licences an image may carry, as a closed vocabulary.

    A real Postgres enum for ADR-0088's reason for `DocumentKind`, but with more force
    behind it: an unretrieved row is a quality problem, whereas a typo'd licence is a
    **legal** one — it would let material Spoin may not use commercially look
    indistinguishable from material it may (task 0040, Phase 2).

    Two exclusions are worth stating here rather than only in the contract, because both
    are counter-intuitive enough to be "fixed" by someone reading this list:

    - **NC (NonCommercial)** is absent because Spoin is commercial (owner, 2026-09-05).
    - **ND (NoDerivatives)** is absent because serving an image at card width crops and
      resizes it, which produces a derivative work. ND is disqualified by the
      architecture, not by policy — it cannot be re-admitted by deciding to be careful.
    """

    CC0 = "cc0"
    PUBLIC_DOMAIN = "public-domain"
    CC_BY = "cc-by"
    CC_BY_SA = "cc-by-sa"
    UNSPLASH = "unsplash"
    PEXELS = "pexels"
    PIXABAY = "pixabay"


class Document(Base, UUIDPrimaryKey, CreatedAt):
    """One authored source file, and enough provenance to cite it.

    Provenance is not optional. "We can back with grounding why our material is high
    quality" is a claim about *citability*, so the citation has to be storable —
    ADR-0089's whole argument for recording chunk IDs on a card dead-ends here if a
    chunk cannot say where it came from.
    """

    __tablename__ = "document"
    __table_args__ = (
        #: The hierarchy is not optional for subject matter, and a CHECK is the only
        #: thing that keeps that true. `spoin_canon` is exempt because canon is about
        #: Spoin rather than about a field — it has no category and no scope, and
        #: forcing it to invent one would put junk values in the columns the
        #: authoring procedure reads back to offer the owner real options.
        CheckConstraint(
            "kind <> 'topic_source' OR (category IS NOT NULL AND scope IS NOT NULL)",
            name="topic_source_has_category_and_scope",
        ),
        #: Read by the authoring procedure's intake step, which lists the categories
        #: already in use before proposing a new one
        #: (docs/the_spoin_universe/procedure.md, Phase A).
        Index("ix_document_category_sub_category", "category", "sub_category"),
    )

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

    #: ADR-0091: the organising level above topics — "mathematics", "computer
    #: science". It exists nowhere in `spoin_db_2`; the corpus is the first thing in
    #: this project that needed one, so this column is where it is introduced.
    #:
    #: Nullable only so `spoin_canon` can sit outside the subject hierarchy — the
    #: CHECK constraint above makes it mandatory for everything else. Stored
    #: normalized (lowercased, non-alphanumerics to spaces) by the same
    #: `normalize_topic_text` that produces `chunk.topic_tags`, so "Computer Science"
    #: and "computer-science" cannot become two categories.
    category: Mapped[str | None] = mapped_column(String(120), nullable=True)

    #: Optional even for subject matter: "science" earns "biology"/"physics";
    #: "history" would only earn "history". A level that restates its parent is noise,
    #: so the absence of a value is meaningful rather than missing data.
    sub_category: Mapped[str | None] = mapped_column(String(120), nullable=True)

    #: Survey or topic — breadth or depth. Nullable for the same reason as `category`
    #: and mandatory under the same CHECK.
    scope: Mapped[DocumentScope | None] = mapped_column(
        Enum(
            DocumentScope,
            name="document_scope",
            values_callable=lambda e: [member.value for member in e],
        ),
        nullable=True,
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

    #: The `##` heading this chunk was cut at, stored separately even though
    #: `contextual_text` already prefixes it into `text`.
    #:
    #: It is what makes a chunk ADDRESSABLE by a human. An authored curriculum declares
    #: its grounding as `<document path>#<exact heading>` (authored-curriculum.md), and
    #: resolving that to rows has to be a join, not a `LIKE` against the prefix of
    #: `text` -- which would match a heading that is another's prefix and would break
    #: the moment the header format changed. Nullable only for chunks written before
    #: this column existed; re-ingestion with `--force` fills them.
    heading: Mapped[str | None] = mapped_column(Text, nullable=True)

    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)

    #: Which model produced `embedding`. NOT NULL, unlike its counterparts on
    #: `spoin_db_2` — a chunk always has a vector here, so it can always name the model
    #: that made it, and the pair is enforced by the column rather than by a CHECK.
    #:
    #: ADR-0097 added this to `card`, `question` and `topic` and left the corpus
    #: without it, which is task 0039's failure mode on the database that grounds every
    #: prompt: ingest once with `--embedder hash` and every retrieval is noise that
    #: raises nothing. Answering "which model made these vectors?" cost a GPU model
    #: load and a cosine comparison on 2026-09-05. It should cost a SELECT.
    embedding_model: Mapped[str] = mapped_column(String(120), nullable=False)

    #: Normalized topic slugs, produced by `frog.embeddings.normalize_topic_text` at
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
        #: How an authored curriculum's `<path>#<heading>` grounding reference
        #: resolves to rows. Composite because a heading is only unique within its
        #: document -- "Overview" appears in many.
        Index("ix_chunk_document_id_heading", "document_id", "heading"),
        #: GIN because `topic_tags` is an array searched with containment operators.
        #: Present even though the filter is off by default — Phase 3 inspects
        #: cross-topic retrieval scores, and turning the filter on should not then
        #: require a migration to be usable.
        Index("ix_chunk_topic_tags", "topic_tags", postgresql_using="gin"),
    )


class Image(Base, UUIDPrimaryKey, CreatedAt):
    """One open-licensed photograph a card may carry (ADR-0095, task 0040).

    **Not a `Document`, despite arriving as a manifest file.** A document is chunked and
    retrieved as prose that grounds what a card *says*; an image is retrieved whole as
    something a card *shows*, and it carries obligations prose does not — an attribution
    that must be displayed, and a licence that decides whether it may be used at all.
    Folding it into `document` would put both of those in nullable columns that only one
    kind of row ever fills, which is the shape ADR-0088 rejected for `author`/`licence`
    in the first place.

    **The model never sees this table.** Assignment is a server-side retrieval query run
    after a card is drafted (ADR-0095): the writer is not told images exist, so it can
    neither request one nor hallucinate a reference to one.
    """

    __tablename__ = "image"

    #: The manifest this entry was delivered in, mirroring `document.source_path`.
    #: Not unique — one manifest carries many images — but indexed with the entry's
    #: identity below so re-ingesting a manifest can find its rows in one scan.
    manifest_path: Mapped[str] = mapped_column(String(1000), nullable=False)

    #: The image's IDENTITY, and why re-ingestion is idempotent without a per-file
    #: hash: a manifest is a list, so a document-style whole-file hash would rebuild
    #: all 76 rows because one description was reworded, and every rebuilt row would
    #: need re-embedding on a GPU. Unique globally rather than per manifest — the same
    #: photograph delivered under two subjects is one catalog entry, not two, and
    #: assignment's "not already used in this topic" filter depends on that being true.
    source_url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)

    #: sha256 of the entry's own fields. Unchanged hash, skip; changed hash, update the
    #: row and re-embed. The same reasoning as `document.content_hash`, applied one
    #: level down because the unit of delivery and the unit of meaning differ here.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    #: Shown when a card cites the image. Human-readable, not an identifier.
    title: Mapped[str] = mapped_column(String(500), nullable=False)

    #: **The highest-leverage field in the catalog**: it is what gets embedded, and
    #: what a drafted card's text is matched against. Not alt text and not a caption —
    #: "Saturn's rings backlit by the sun, photographed by Cassini from within the
    #: planet's shadow" matches a card about ring composition; "Saturn" matches nothing
    #: in particular. The contract says so at length, because getting it wrong fails
    #: silently as mediocre assignments rather than loudly as an error.
    description: Mapped[str] = mapped_column(Text, nullable=False)

    #: The page the image was found on — what a human re-checks the licence against.
    #: Distinct from `source_url`, which is the file itself: a direct file URL usually
    #: states no licence at all, so storing only it would make the claim unverifiable.
    source_page: Mapped[str] = mapped_column(Text, nullable=False)

    licence: Mapped[ImageLicence] = mapped_column(
        Enum(
            ImageLicence,
            name="image_licence",
            values_callable=lambda e: [member.value for member in e],
        ),
        nullable=False,
    )

    #: The exact string to display. NOT NULL even for `cc0` and `public-domain`, where
    #: it is "public domain" rather than empty: CC BY and CC BY-SA make display a
    #: licence condition, and a renderer that has to decide whether attribution is
    #: required is a renderer that will get it wrong for one licence.
    attribution: Mapped[str] = mapped_column(Text, nullable=False)

    #: Same normalized hierarchy as `document` (ADR-0091), inherited from the manifest
    #: header rather than repeated per entry. NOT NULL, unlike on `document`: there is
    #: no image equivalent of `spoin_canon` sitting outside the subject hierarchy, so
    #: the exemption that forces those columns nullable does not apply here.
    category: Mapped[str] = mapped_column(String(120), nullable=False)
    sub_category: Mapped[str | None] = mapped_column(String(120), nullable=True)

    topic_tags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")

    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)

    #: Which model produced `embedding`, for `chunk.embedding_model`'s reason — a
    #: catalog embedded with `HashEmbedder` assigns uniformly irrelevant images and
    #: looks completely normal doing it (task 0039).
    embedding_model: Mapped[str] = mapped_column(String(120), nullable=False)

    #: Where the image is actually served from once uploaded, or NULL while it is still
    #: served from `source_url`.
    #:
    #: Nullable because the upload step is deliberately NOT built yet: the constraint
    #: Cloudinary exists to solve is bandwidth at user scale (task 0040), and there are
    #: no users. Adding the column now means the upload lands later as a backfill
    #: rather than as a migration plus a full re-ingest, which would re-embed the whole
    #: catalog on a GPU to write one URL per row.
    cloudinary_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        #: Assignment filters by the topic's category before ranking, so this is the
        #: index that query actually uses.
        Index("ix_image_category_sub_category", "category", "sub_category"),
        #: Re-ingesting one manifest reads back exactly its own rows.
        Index("ix_image_manifest_path", "manifest_path"),
        Index("ix_image_topic_tags", "topic_tags", postgresql_using="gin"),
    )
