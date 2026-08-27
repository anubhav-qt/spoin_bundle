"""Shared model-availability state (ADR-0065)

Moves the quota governor's "this model has stopped answering" flag out of
process memory and into the database, for the same reason ADR-0058 moved the
RPM window: the API and the worker each held their own view, so a 504 outage
one process had already discovered was rediscovered -- at the cost of another
full timeout -- by every other process and every other pool listing the same
model.

Revision ID: d1a93f6b25e7
Revises: b8c4f1e07d92
Create Date: 2026-08-28

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "d1a93f6b25e7"
down_revision: str | None = "b8c4f1e07d92"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "model_unavailable",
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("excluded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(length=256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("model"),
    )


def downgrade() -> None:
    op.drop_table("model_unavailable")
