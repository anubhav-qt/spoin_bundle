"""Card provenance (ADR-0089): which corpus chunks grounded this card

Additive only -- a nullable column and one index. Existing rows keep NULL,
which is the correct value for them: they were written before retrieval
existed, and NULL says exactly that. `[]` is a different fact and is written by
the pipeline when retrieval RAN and returned nothing.

GIN rather than btree because the question this exists to answer is a
containment one -- "which cards did this retracted chunk ground?"
(rag-design-space 3.12). ADR-0089 rejected free-text provenance for the same
reason: a citation nothing can query is not a citation.

No foreign key, and there cannot be one: `chunk` lives in `the_spoin_universe`,
a different database (ADR-0088). A dangling id is therefore possible, and what
it should mean is an open question ADR-0089 names rather than settles.

Revision ID: a1b2c3d4e5f6
Revises: c4d5e6f708a9
Create Date: 2026-09-05

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "c4d5e6f708a9"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "card",
        sa.Column(
            "grounded_chunk_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_card_grounded_chunk_ids",
        "card",
        ["grounded_chunk_ids"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_card_grounded_chunk_ids", table_name="card")
    op.drop_column("card", "grounded_chunk_ids")
