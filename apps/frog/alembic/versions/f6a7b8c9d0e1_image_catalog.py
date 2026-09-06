"""image: the open-licensed catalog a card's photograph comes from

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-09-06

ADR-0095 and task 0040. A separate table from `document` rather than a `kind` on it:
an image is retrieved whole rather than chunked, and it carries a licence and an
attribution that must be displayed — obligations prose does not have, and which would
sit in nullable columns only one kind of row ever fills.

`licence` is a real Postgres enum for the reason ADR-0088 made `document.kind` one,
with more force: a typo'd licence is a legal exposure rather than an unretrieved row.

`cloudinary_url` is created nullable and stays empty for now. The upload step is
deliberately unbuilt — the constraint Cloudinary solves is bandwidth at user scale and
there are no users — so the column exists to let that land later as a backfill rather
than as a migration plus a full re-ingest that would re-embed the catalog on a GPU.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "f6a7b8c9d0e1"
down_revision: str | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Written out rather than imported from `frog.universe.models`: a migration is a
#: record of what the schema was at this revision, and importing the live enum would
#: make this file silently change meaning the day a member is added.
_LICENCES = ("cc0", "public-domain", "cc-by", "cc-by-sa", "unsplash", "pexels", "pixabay")


def upgrade() -> None:
    licence = postgresql.ENUM(*_LICENCES, name="image_licence", create_type=False)
    licence.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "image",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("manifest_path", sa.String(length=1000), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("source_page", sa.Text(), nullable=False),
        sa.Column("licence", licence, nullable=False),
        sa.Column("attribution", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=120), nullable=False),
        sa.Column("sub_category", sa.String(length=120), nullable=True),
        sa.Column(
            "topic_tags",
            postgresql.ARRAY(sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("embedding", Vector(1024), nullable=False),
        sa.Column("embedding_model", sa.String(length=120), nullable=False),
        sa.Column("cloudinary_url", sa.Text(), nullable=True),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_image"),
        #: The entry's identity. Unique GLOBALLY, not per manifest: the same photograph
        #: delivered under two subjects is one catalog entry, and assignment's
        #: "not already used in this topic" filter depends on that.
        sa.UniqueConstraint("source_url", name="uq_image_source_url"),
    )
    op.create_index("ix_image_category_sub_category", "image", ["category", "sub_category"])
    op.create_index("ix_image_manifest_path", "image", ["manifest_path"])
    op.create_index("ix_image_topic_tags", "image", ["topic_tags"], postgresql_using="gin")


def downgrade() -> None:
    """Refuses, in line with the rest of this chain.

    See `a1b2c3d4e5f6_initial_universe_schema.py`. `the_spoin_universe` has no
    downgrade path: recreate the database and re-ingest instead (ADR-0088).
    """

    raise RuntimeError(
        "the_spoin_universe has no downgrade path: recreate the database and "
        "re-ingest instead (ADR-0088)."
    )
