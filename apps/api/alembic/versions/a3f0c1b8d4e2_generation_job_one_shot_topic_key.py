"""generation_job simplifies to one-shot, topic-keyed (ADR-0026)

Drops `generation_job.kind` (curriculum | cards | questions never meant
anything downstream — the pipeline always does curriculum-if-needed-then-cards
regardless) and `generation_job.subtopic_id` (the old per-subtopic refill
coalescing key ADR-0007 introduced — there is no more recurring refill to
coalesce, since ADR-0026 made generation a one-shot run per topic). The
coalescing lock moves to `topic_id`: a topic needs at most one outstanding job,
ever.

Revision ID: a3f0c1b8d4e2
Revises: d891a4c2e6f0
Create Date: 2026-08-17 00:00:02.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a3f0c1b8d4e2"
down_revision: str | None = "d891a4c2e6f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index(
        "uq_generation_job_subtopic_pending",
        table_name="generation_job",
        postgresql_where=sa.text("status IN ('pending', 'running')"),
    )
    op.drop_constraint(
        "fk_generation_job_subtopic_id_subtopic", "generation_job", type_="foreignkey"
    )
    op.drop_column("generation_job", "subtopic_id")
    op.drop_column("generation_job", "kind")

    op.create_index(
        "uq_generation_job_topic_pending",
        "generation_job",
        ["topic_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'running')"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_generation_job_topic_pending",
        table_name="generation_job",
        postgresql_where=sa.text("status IN ('pending', 'running')"),
    )

    op.add_column("generation_job", sa.Column("kind", sa.String(32), nullable=True))
    op.execute("UPDATE generation_job SET kind = 'cards' WHERE kind IS NULL")
    op.alter_column("generation_job", "kind", nullable=False)

    op.add_column("generation_job", sa.Column("subtopic_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_generation_job_subtopic_id_subtopic",
        "generation_job",
        "subtopic",
        ["subtopic_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.create_index(
        "uq_generation_job_subtopic_pending",
        "generation_job",
        ["subtopic_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'running')"),
    )
