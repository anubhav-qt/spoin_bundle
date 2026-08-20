"""add_daily_card_goal

Revision ID: b4e17c92da03
Revises: 697860abfcc3
Create Date: 2026-08-21 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'b4e17c92da03'
down_revision: str | None = '697860abfcc3'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # NOT NULL with a server_default rather than a nullable column: existing
    # rows need a value, and "no goal set" and "goal of 10" are not usefully
    # different states for a target the user can change at any time. The
    # default matches the model's own (domain/models/topic.py), so a row
    # created by the ORM and a row backfilled here agree.
    op.add_column(
        'app_user',
        sa.Column('daily_card_goal', sa.Integer(), nullable=False, server_default='10'),
    )


def downgrade() -> None:
    op.drop_column('app_user', 'daily_card_goal')
