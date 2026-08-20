"""defer_avatar_and_denormalize_flag

Revision ID: c5f28d13eb14
Revises: b4e17c92da03
Create Date: 2026-08-21 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'c5f28d13eb14'
down_revision: str | None = 'b4e17c92da03'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # `has_avatar_image` used to be computed per request by testing
    # `avatar_image is not None`, which meant every caller that wanted the flag
    # dragged the whole blob along. Storing it lets `avatar_image` become a
    # deferred column (see domain/models/topic.py).
    op.add_column(
        'app_user',
        sa.Column(
            'has_avatar_image', sa.Boolean(), nullable=False, server_default='false'
        ),
    )
    op.add_column(
        'app_user', sa.Column('avatar_media_type', sa.String(length=32), nullable=True)
    )
    # Backfill from the blob itself so existing uploads keep rendering.
    # image/jpeg for the media type is what the old download endpoint
    # hardcoded, so pre-existing rows keep behaving exactly as they did.
    op.execute(
        "UPDATE app_user SET has_avatar_image = (avatar_image IS NOT NULL), "
        "avatar_media_type = CASE WHEN avatar_image IS NOT NULL THEN 'image/jpeg' END"
    )


def downgrade() -> None:
    op.drop_column('app_user', 'avatar_media_type')
    op.drop_column('app_user', 'has_avatar_image')
