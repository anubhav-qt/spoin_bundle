"""document hierarchy: category, sub_category, scope

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-09-05

ADR-0091. Categories and sub-categories were front-matter-only when the authoring
procedure was written; this makes them real columns, so the intake step can read back
the categories already in use instead of trusting a directory listing.

A separate migration rather than an edit to the initial one: the initial chain may
already have been applied to `the_spoin_universe` by the owner, and an amended
migration that has already run is a migration that silently never runs again.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    scope = sa.Enum("survey", "topic", name="document_scope")
    scope.create(op.get_bind(), checkfirst=True)

    op.add_column("document", sa.Column("category", sa.String(length=120), nullable=True))
    op.add_column("document", sa.Column("sub_category", sa.String(length=120), nullable=True))
    op.add_column("document", sa.Column("scope", scope, nullable=True))

    op.create_index(
        "ix_document_category_sub_category", "document", ["category", "sub_category"]
    )

    # Nullable columns plus a CHECK, rather than NOT NULL: `spoin_canon` documents sit
    # outside the subject hierarchy and have neither a category nor a scope. Making
    # them invent one would put junk into the very columns the authoring procedure
    # reads back to offer the owner real options.
    #
    # `op.f` marks the name as final. Without it the metadata's naming convention
    # prefixes it a second time, and the constraint this creates is not the one
    # `Document.__table_args__` declares -- which autogenerate then reports as a
    # phantom diff forever.
    op.create_check_constraint(
        op.f("ck_document_topic_source_has_category_and_scope"),
        "document",
        "kind <> 'topic_source' OR (category IS NOT NULL AND scope IS NOT NULL)",
    )


def downgrade() -> None:
    """Refuses, in line with the rest of this chain.

    See `a1b2c3d4e5f6_initial_universe_schema.py`. `the_spoin_universe` has no
    downgrade path: the recovery move is to recreate the database and re-ingest the
    corpus, which is explicit and reviewable, rather than an `alembic downgrade` that
    reads as routine in a shell history.
    """

    raise RuntimeError(
        "the_spoin_universe has no downgrade path: recreate the database and "
        "re-ingest instead (ADR-0088)."
    )
