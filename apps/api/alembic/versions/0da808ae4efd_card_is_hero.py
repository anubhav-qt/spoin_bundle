"""card is_hero

Adds `card.is_hero`, replacing the frontend's old "first card in this feed
station" heuristic for which card renders as the visual anchor. See
ADR-0017 and docs/tasks/0006-curated-hero-cards.md — the intended real
mechanism is a content-planning step designating exactly one hero card per
subtopic; today's only writer is the fixture seeder, which marks the first
card listed per subtopic.

Revision ID: 0da808ae4efd
Revises: bda2147cef2a
Create Date: 2026-08-16 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0da808ae4efd"
down_revision: str | None = "bda2147cef2a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "card",
        sa.Column("is_hero", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("card", "is_hero")
