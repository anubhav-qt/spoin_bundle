"""Load balancer (ADR-0084): drop the DB-backed quota state

The generation pipeline is now the only process on the key pool, so the
per-minute window (`quota_request`) and the model-unavailable set
(`model_unavailable`) move into memory in `load_balancer.py`. `quota_ledger`
keeps only the durable per-day count -- `exhausted_at` and `cooldown_until` were
same-day-only state the balancer never re-reads.

`downgrade()` recreates the structures, not their data: every row in them is
worthless after 60 seconds (`quota_request`) or the next probe
(`model_unavailable`), and the dropped ledger columns are same-day state.

Revision ID: c4d5e6f708a9
Revises: 07b6c1a3cb76
Create Date: 2026-09-03

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "c4d5e6f708a9"
down_revision: str | None = "07b6c1a3cb76"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.drop_index("ix_quota_request_backend_sent_at", table_name="quota_request")
    op.drop_table("quota_request")
    op.drop_table("model_unavailable")
    op.drop_column("quota_ledger", "exhausted_at")
    op.drop_column("quota_ledger", "cooldown_until")


def downgrade() -> None:
    op.add_column(
        "quota_ledger",
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "quota_ledger",
        sa.Column("exhausted_at", sa.DateTime(timezone=True), nullable=True),
    )
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
