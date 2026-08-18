"""generation_job.progress for the live request-a-topic streaming UI

Best-effort, incrementally-written JSON: curriculum topic name, then one
entry per subtopic-tier with card/question done/target counts. Written by
generation/pipeline.py as the run proceeds; read by GET
/topics/{topic_id}/generation-progress for the frontend to poll.

Revision ID: 7b3d9c4e1a08
Revises: 077f410c5134
Create Date: 2026-08-18 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "7b3d9c4e1a08"
down_revision: str | None = "077f410c5134"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "generation_job",
        sa.Column(
            "progress",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("generation_job", "progress")
