"""subtopic groups and quota ledger exhaustion metadata

Adds `subtopic.subtopic_group_id` — links sibling Subtopic rows across difficulty
tiers that the curriculum pass decided belong to the same conceptual slot, so
generation can see existing titles across tiers (ADR-0007) rather than only within
one row. Existing rows each get their own fresh group id (a group of one), since
there is no way to infer historical grouping after the fact.

Also widens `quota_ledger.backend` (32 -> 64 chars, room for `"gemini:{key_index}"`
values) and adds `quota_ledger.exhausted_at`.

Revision ID: d891a4c2e6f0
Revises: c2a5e9f31b47
Create Date: 2026-08-17 00:00:01.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d891a4c2e6f0"
down_revision: str | None = "c2a5e9f31b47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("subtopic", sa.Column("subtopic_group_id", postgresql.UUID(), nullable=True))
    op.execute("UPDATE subtopic SET subtopic_group_id = gen_random_uuid() WHERE subtopic_group_id IS NULL")
    op.alter_column("subtopic", "subtopic_group_id", nullable=False)
    op.create_index("ix_subtopic_group_id", "subtopic", ["subtopic_group_id"])

    op.alter_column("quota_ledger", "backend", type_=sa.String(64))
    op.add_column("quota_ledger", sa.Column("exhausted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("quota_ledger", "exhausted_at")
    op.alter_column("quota_ledger", "backend", type_=sa.String(32))

    op.drop_index("ix_subtopic_group_id", table_name="subtopic")
    op.drop_column("subtopic", "subtopic_group_id")
