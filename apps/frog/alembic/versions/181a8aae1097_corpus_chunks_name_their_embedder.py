"""corpus chunks name their embedder

ADR-0097 put an `embedding_model` stamp on `card`, `question` and `topic` and left the
corpus without one — task 0039's failure mode on the one database that grounds every
prompt. Ingest once with `--embedder hash` and every retrieval becomes noise that
raises nothing, because a hash vector has the right dimension and the wrong meaning.

`NOT NULL` rather than the CHECK its counterparts use: `chunk.embedding` is itself
`NOT NULL`, so a chunk always has a vector and can always name what made it.

**The backfill value is measured, not assumed.** On 2026-09-05 a stored chunk vector
was compared against both candidates, re-embedding its own text:

    cosine(stored, Qwen/Qwen3-Embedding-0.6B) = 1.0001
    cosine(stored, HashEmbedder(1024))        = -0.0074

Every chunk in the corpus was written by one ingestion run of one embedder, so that
settles all 933 of them. Stamping rows on a belief about how they were made is exactly
the mistake this column exists to prevent; the cosine is why this is not that. Anyone
re-running against a corpus whose provenance is not established should re-ingest
instead — `frog.ingest` is idempotent by content hash, and `--force` rebuilds.

Revision ID: 181a8aae1097
Revises: c3d4e5f6a7b8
Create Date: 2026-09-05 11:46:20.331020
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "181a8aae1097"
down_revision: str | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: What the cosine comparison above identified. Not read from settings: a migration
#: that stamps rows with whatever the environment happens to say today would record
#: the running config rather than the fact.
_MEASURED = "Qwen/Qwen3-Embedding-0.6B"


def upgrade() -> None:
    # Nullable first: the column is NOT NULL in the end, and 933 rows already exist.
    op.add_column("chunk", sa.Column("embedding_model", sa.String(length=120), nullable=True))
    op.execute(sa.text("UPDATE chunk SET embedding_model = :model").bindparams(model=_MEASURED))
    op.alter_column("chunk", "embedding_model", nullable=False)


def downgrade() -> None:
    op.drop_column("chunk", "embedding_model")
