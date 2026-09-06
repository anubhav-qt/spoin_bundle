"""chunk.heading: a chunk becomes addressable by a human

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-09-06

An authored curriculum declares its grounding per tier as `<document path>#<exact `##`
heading>` (docs/architecture/authored-curriculum.md). Resolving that to rows has to be
a join. Matching the front of `chunk.text` instead would pass a heading that is another
heading's prefix, and would break silently the day `contextual_text`'s header format
changes.

Nullable, and no backfill in SQL: the heading is not recoverable from the stored text
without re-parsing the source document, and re-ingestion already does that. `make
corpus-ingest --force` fills the column; until then a null heading simply resolves
nothing, which is visible rather than wrong.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: str | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("chunk", sa.Column("heading", sa.Text(), nullable=True))
    #: The lookup an authored grounding reference performs: given a document, find the
    #: chunk with this heading. Composite because the heading is only unique within a
    #: document -- "Overview" appears in many.
    op.create_index("ix_chunk_document_id_heading", "chunk", ["document_id", "heading"])


def downgrade() -> None:
    """Refuses, in line with the rest of this chain.

    See `a1b2c3d4e5f6_initial_universe_schema.py`. `the_spoin_universe` has no
    downgrade path: recreate the database and re-ingest instead (ADR-0088).
    """

    raise RuntimeError(
        "the_spoin_universe has no downgrade path: recreate the database and "
        "re-ingest instead (ADR-0088)."
    )
