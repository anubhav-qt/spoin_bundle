"""card archetype

Adds `card.archetype`, a text array of content-shape tags ("code", "diagram",
"comparison", any subset, `[]` for plain prose) — see
spoin/content/archetype.py and ADR-0017. It is derived deterministically from
`body` itself, never LLM-authored, so there is nothing to backfill from a
generation-time field: existing rows simply get the empty-array default until
something re-derives it (seed.py does this on every run for fixture cards).

Revision ID: bda2147cef2a
Revises: 89eeadec73d8
Create Date: 2026-08-16 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "bda2147cef2a"
down_revision: str | None = "89eeadec73d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "card",
        sa.Column(
            "archetype",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    op.drop_column("card", "archetype")
