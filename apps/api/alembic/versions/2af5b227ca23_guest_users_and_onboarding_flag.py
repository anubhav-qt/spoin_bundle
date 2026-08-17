"""guest users and onboarding flag

Revision ID: 2af5b227ca23
Revises: 953a51403237
Create Date: 2026-08-18 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2af5b227ca23"
down_revision: str | None = "953a51403237"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Postgres treats every NULL as distinct under a UNIQUE constraint, so this
    # lets many guest users coexist with `email IS NULL` — see domain/models/topic.py.
    op.alter_column(
        "app_user",
        "email",
        existing_type=sa.String(length=320),
        nullable=True,
    )
    op.add_column(
        "app_user",
        sa.Column(
            "onboarding_complete",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.alter_column("app_user", "onboarding_complete", server_default=None)


def downgrade() -> None:
    op.drop_column("app_user", "onboarding_complete")
    op.alter_column(
        "app_user",
        "email",
        existing_type=sa.String(length=320),
        nullable=False,
    )
