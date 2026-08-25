"""Shared per-minute quota window (ADR-0058)

Moves the quota governor's RPM window and rate-limit cooldowns out of process
memory and into the database, so concurrent processes (the API serving topic
matching and quiz grading, the worker generating) stop each permitting the full
per-minute ceiling on the same key.

Revision ID: b8c4f1e07d92
Revises: a91d5e73c204
Create Date: 2026-08-25

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "b8c4f1e07d92"
down_revision: str | None = "a91d5e73c204"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "quota_ledger",
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "quota_request",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("backend", sa.String(length=64), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_quota_request_backend_sent_at",
        "quota_request",
        ["backend", "sent_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_quota_request_backend_sent_at", table_name="quota_request")
    op.drop_table("quota_request")
    op.drop_column("quota_ledger", "cooldown_until")
