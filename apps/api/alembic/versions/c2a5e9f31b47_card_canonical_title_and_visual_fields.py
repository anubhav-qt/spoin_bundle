"""card canonical_title and visual fields

Adds `card.canonical_title` (ADR-0022) and `card.visual_id` / `card.visual_slots`
(ADR-0021). Per CLAUDE.md's sequencing note: these fields ride along with the
generation pipeline rather than landing after it, so the pipeline never has to
backfill/regenerate the corpus to pick them up later.

`canonical_title` is backfilled from `title` for existing rows so the column can be
NOT NULL — this is a placeholder, not a real canonical title (fixture and
seed-generated cards were written before ADR-0022 existed). A future regeneration
pass is expected to replace these; see the "do the schema half now" reasoning in
CLAUDE.md's rename/catch note.

`visual_id` / `visual_slots` stay nullable with no backfill: the ASCII scene catalog
they'd select from doesn't exist yet (docs/tasks table, "ASCII scene catalog").

Revision ID: c2a5e9f31b47
Revises: 0da808ae4efd
Create Date: 2026-08-17 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c2a5e9f31b47"
down_revision: str | None = "0da808ae4efd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("card", sa.Column("canonical_title", sa.String(160), nullable=True))
    op.execute("UPDATE card SET canonical_title = title WHERE canonical_title IS NULL")
    op.alter_column("card", "canonical_title", nullable=False)

    op.add_column("card", sa.Column("visual_id", sa.String(64), nullable=True))
    op.add_column("card", sa.Column("visual_slots", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("card", "visual_slots")
    op.drop_column("card", "visual_id")
    op.drop_column("card", "canonical_title")
