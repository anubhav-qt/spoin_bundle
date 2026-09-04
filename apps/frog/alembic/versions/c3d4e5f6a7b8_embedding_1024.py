"""chunk embeddings move to 1024 dimensions

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-09-05

ADR-0092: the embedder becomes `Qwen/Qwen3-Embedding-0.6B` (1024-d), replacing
`bge-small-en-v1.5` (384-d). Task 0039 forced a re-embed regardless, which is what
makes the model change cost approximately nothing.

Written as a type change rather than a drop/add because `the_spoin_universe` may
already exist with the earlier chain applied. Any rows present are re-embedded by
ingestion, not migrated -- a vector cannot be converted between models.
"""

from __future__ import annotations

from collections.abc import Sequence

import pgvector.sqlalchemy
from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # USING NULL rather than a cast: 384-d vectors from a different model carry no
    # information a 1024-d Qwen3 vector could use, and silently keeping garbage is
    # exactly the failure task 0039 documents. Re-ingestion refills them.
    op.execute("ALTER TABLE chunk ALTER COLUMN embedding TYPE vector(1024) USING NULL")
    op.alter_column(
        "chunk",
        "embedding",
        existing_type=pgvector.sqlalchemy.Vector(dim=1024),
        nullable=False,
    )


def downgrade() -> None:
    """Refuses, in line with the rest of this chain -- see the initial migration."""

    raise RuntimeError(
        "the_spoin_universe has no downgrade path: recreate the database and "
        "re-ingest instead (ADR-0088)."
    )
