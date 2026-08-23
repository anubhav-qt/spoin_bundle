"""session scoped topic shares

Revision ID: a91d5e73c204
Revises: c5f28d13eb14
Create Date: 2026-08-24 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'a91d5e73c204'
down_revision: str | None = 'c5f28d13eb14'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('user_session_topic_signal',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('topic_id', sa.UUID(), nullable=False),
    sa.Column('score', sa.Float(), nullable=False),
    sa.Column('last_event_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['topic_id'], ['topic.id'], name=op.f('fk_user_session_topic_signal_topic_id_topic'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['app_user.id'], name=op.f('fk_user_session_topic_signal_user_id_app_user'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'topic_id', name=op.f('pk_user_session_topic_signal'))
    )
    # server_default='' rather than a nullable column plus a backfill: every
    # existing plan predates share fingerprinting, and an empty fingerprint never
    # matches a computed one, so each user's plan rebuilds once on their next read
    # -- which is exactly the desired migration behaviour.
    op.add_column(
        'feed_plan',
        sa.Column('share_fingerprint', sa.String(length=64), nullable=False, server_default=''),
    )


def downgrade() -> None:
    op.drop_column('feed_plan', 'share_fingerprint')
    op.drop_table('user_session_topic_signal')
