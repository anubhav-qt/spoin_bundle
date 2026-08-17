"""rejected_card table (ADR-0030)

The two-pass quality gate (structural check -> correction -> near-dup ->
verification) needs somewhere to put a draft that never becomes a `Card` row.
Every draft ends as exactly one of: an ACTIVE `Card`, or a row here.

Revision ID: e7c1a9d3f256
Revises: a3f0c1b8d4e2
Create Date: 2026-08-17 00:00:03.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e7c1a9d3f256"
down_revision: str | None = "a3f0c1b8d4e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rejected_card",
        sa.Column("topic_id", sa.UUID(), nullable=False),
        sa.Column("subtopic_id", sa.UUID(), nullable=False),
        sa.Column(
            "requested_difficulty",
            postgresql.ENUM(
                "beginner", "intermediate", "advanced", name="difficulty", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("canonical_title", sa.String(length=160), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "stage",
            sa.Enum("structural", "near_duplicate", "verification", name="rejection_stage"),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "gen_meta",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["subtopic_id"], ["subtopic.id"], name=op.f("fk_rejected_card_subtopic_id_subtopic"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["topic_id"], ["topic.id"], name=op.f("fk_rejected_card_topic_id_topic"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rejected_card")),
    )
    op.create_index(
        "ix_rejected_card_subtopic_id", "rejected_card", ["subtopic_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_rejected_card_subtopic_id", table_name="rejected_card")
    op.drop_table("rejected_card")
    op.execute("DROP TYPE IF EXISTS rejection_stage")
