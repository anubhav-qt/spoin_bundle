"""one embedder, one vector space

Widens every vector column from 384 to 1024 and stamps each with the model that
produced it. ADR-0097 collapsed the two embedders into one (`Qwen3-Embedding-0.6B`),
and 1024 is the dimension `the_spoin_universe`'s chunks were already ingested at.

**This migration discards vector data.** Postgres cannot cast `vector(384)` to
`vector(1024)` — there is no meaningful value to widen to — so each column is nulled
before the type change and the rows must be re-embedded afterwards. When it was
written that cost nothing: task 0039 had just established that every vector in
`spoin_db_2` was `HashEmbedder` output, semantically meaningless by its own docstring.
Anywhere that is NOT true, re-embed before relying on a similarity search again.

The `embedding_model` stamp is task 0039's durable half. Without it a column can hold
two incomparable kinds of vector and nothing — no query, no log line, no test — can
tell, which is precisely how 5,491 hash vectors went unnoticed.

Revision ID: feded8588fd8
Revises: a1b2c3d4e5f6
Create Date: 2026-09-05 09:44:04.799601
"""

from __future__ import annotations

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op

revision: str = "feded8588fd8"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: table, vector column.
_VECTORS = [
    ("card", "content_embedding"),
    ("question", "embedding"),
    ("topic", "embedding"),
]


def upgrade() -> None:
    for table, column in _VECTORS:
        # The type change cannot carry the values across, and an implicit failure
        # here would read as a pgvector bug rather than the deliberate loss it is.
        op.execute(f"UPDATE {table} SET {column} = NULL")  # noqa: S608
        op.alter_column(
            table,
            column,
            existing_type=pgvector.sqlalchemy.vector.VECTOR(dim=384),
            type_=pgvector.sqlalchemy.vector.VECTOR(dim=1024),
            existing_nullable=True,
        )
        op.add_column(table, sa.Column("embedding_model", sa.String(length=120), nullable=True))


def downgrade() -> None:
    for table, column in reversed(_VECTORS):
        op.drop_column(table, "embedding_model")
        op.execute(f"UPDATE {table} SET {column} = NULL")  # noqa: S608
        op.alter_column(
            table,
            column,
            existing_type=pgvector.sqlalchemy.vector.VECTOR(dim=1024),
            type_=pgvector.sqlalchemy.vector.VECTOR(dim=384),
            existing_nullable=True,
        )
