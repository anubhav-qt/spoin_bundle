"""add user_topic accent_hue

Revision ID: 15a1fcbd511d
Revises: 2af5b227ca23
Create Date: 2026-08-18 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '15a1fcbd511d'
down_revision: str | None = '2af5b227ca23'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('user_topic', sa.Column('accent_hue', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('user_topic', 'accent_hue')
