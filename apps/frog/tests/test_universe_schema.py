"""Schema-shape checks for `the_spoin_universe`.

No database: these read the SQLAlchemy metadata. They exist because ADR-0088's schema
decisions are the kind that fail *silently* if they drift — a nullable `source` still
works, a non-unique `source_path` still ingests, and both are only discovered later
when a card turns out to be uncitable or the corpus has quietly doubled.
"""

from __future__ import annotations

from frog.universe.models import EMBEDDING_DIM, Chunk, Document, DocumentKind, DocumentScope


def test_vectors_are_384_dimensional() -> None:
    """ADR-0087: the same space as `card.content_embedding` in `spoin_db_2`.

    This is the one number in the corpus store that cannot be discovered to be wrong
    by testing — mismatched dimensions produce comparisons that are meaningless
    rather than erroneous.
    """

    assert EMBEDDING_DIM == 384
    assert Chunk.__table__.c.embedding.type.dim == 384


def test_provenance_columns_are_not_nullable() -> None:
    """ADR-0089: citability is the claim the corpus exists to make good on. A
    document that cannot say where it came from cannot back a card."""

    for name in ("source", "title", "kind", "source_path", "content_hash", "ingested_at"):
        assert not Document.__table__.c[name].nullable, f"{name} must be NOT NULL"


def test_source_date_is_nullable_and_distinct_from_ingested_at() -> None:
    """Two different facts: when the material is from, and when we read it. Spoin
    canon distilled from our own ADRs has the second and not the first."""

    assert Document.__table__.c.source_date.nullable
    assert not Document.__table__.c.ingested_at.nullable


def test_source_path_is_unique() -> None:
    """ADR-0088's idempotency rests on this: re-ingesting a revised file must update
    one row, not accumulate rows. Without the constraint the duplication is silent
    and the corpus grows a second copy of everything on every redelivery."""

    assert Document.__table__.c.source_path.unique


def test_chunks_cascade_from_their_document() -> None:
    """Re-ingesting a changed document deletes and rebuilds its chunks wholesale.
    Without CASCADE that is a foreign-key error mid-ingestion, or orphaned chunks
    that retrieval happily returns."""

    fk = next(iter(Chunk.__table__.c.document_id.foreign_keys))
    assert fk.ondelete == "CASCADE"


def test_document_kind_has_exactly_the_two_content_kinds() -> None:
    """ADR-0088 made this a real enum so a front-matter typo cannot create a silent
    third kind that nothing retrieves. A third *deliberate* kind is a migration and a
    decision — this test is the place that conversation starts."""

    assert {k.value for k in DocumentKind} == {"spoin_canon", "topic_source"}


def test_topic_tags_are_indexed_for_containment_search() -> None:
    """Retrieval is cross-topic by default (ADR-0088), so this index is unused on
    day one. It exists so that Phase 3's inspection can turn the filter on without
    needing a migration first."""

    gin = [
        index for index in Chunk.__table__.indexes if index.kwargs.get("postgresql_using") == "gin"
    ]
    assert gin, "topic_tags needs a GIN index"
    assert [c.name for c in gin[0].columns] == ["topic_tags"]


def test_the_hierarchy_is_mandatory_for_subject_matter_and_optional_for_canon() -> None:
    """ADR-0091. The columns are nullable, which on its own would let a document be
    filed nowhere — so the invariant lives in a CHECK rather than in the ingester's
    good intentions.

    `spoin_canon` is exempt because canon is about Spoin, not about a field. Forcing
    it to invent a category would put junk into the exact column the authoring
    procedure reads back to offer the owner real options.
    """

    checks = {
        c.name: str(c.sqltext)
        for c in Document.__table__.constraints
        if c.__class__.__name__ == "CheckConstraint"
    }
    #: The metadata naming convention prefixes it (`ck_<table>_<name>`), and the
    #: migration must produce this exact string or autogenerate reports a phantom
    #: diff forever. Asserted in full rather than by substring for that reason.
    name = "ck_document_topic_source_has_category_and_scope"
    assert name in checks

    clause = checks[name]
    assert "topic_source" in clause
    assert "category" in clause and "scope" in clause


def test_scope_has_exactly_survey_and_topic() -> None:
    """Mirrors `topic.is_survey` in spoin_db_2 by value — the corpus is a separate
    database and cannot hold a foreign key to it (ADR-0007, ADR-0088). A third value
    here would mean the two have drifted apart."""

    assert {s.value for s in DocumentScope} == {"survey", "topic"}


def test_category_is_indexed_for_the_intake_step() -> None:
    """The authoring procedure's first question is "which category?", answered by
    reading the categories already in use (procedure.md Phase A). That read happens
    every run; it should not be a sequential scan of the whole corpus."""

    indexed = {tuple(c.name for c in index.columns) for index in Document.__table__.indexes}
    assert ("category", "sub_category") in indexed
