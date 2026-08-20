"""add subtopic card_type_quotas

Revision ID: 7c8d9e0f1a2b
Revises: 7b3d9c4e1a08
Create Date: 2026-08-20 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = '7c8d9e0f1a2b'
down_revision: str | None = '7b3d9c4e1a08'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('subtopic', sa.Column('card_type_quotas', JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column('subtopic', 'card_type_quotas')
