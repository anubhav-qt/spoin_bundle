"""card.visual_kind: store visual asset kind and enforce accompanying visual_id

Task 0040 Phase 3 and ADR-0095. A visual kind enum accompanies visual_id:
a card's visual asset can now be an ASCII gag or an open-licensed image, and the
renderer must know which without relying on implicit format rules like UUID string
detection.

Enforces CheckConstraint "(visual_id IS NULL) = (visual_kind IS NULL)" to guarantee
that a visual asset always states its kind and a kind never exists without an asset.
Existing rows with a non-null visual_id are backfilled to 'ascii' before adding the
constraint.

Revision ID: e6f7a8b9c0d1
Revises: d2e3f4a5b6c7
Create Date: 2026-09-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e6f7a8b9c0d1"
down_revision: str | None = "d2e3f4a5b6c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_VISUAL_KINDS = ("ascii", "image")


def upgrade() -> None:
    visual_kind = postgresql.ENUM(*_VISUAL_KINDS, name="visual_kind", create_type=False)
    visual_kind.create(op.get_bind(), checkfirst=True)

    op.add_column("card", sa.Column("visual_kind", visual_kind, nullable=True))

    #: Backfill existing non-null visual_id cards as ASCII before adding the CHECK constraint,
    #: otherwise existing rows violate the constraint.
    op.execute("UPDATE card SET visual_kind = 'ascii' WHERE visual_id IS NOT NULL")

    op.create_check_constraint(
        "visual_kind_accompanies_visual_id",
        "card",
        "(visual_id IS NULL) = (visual_kind IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_card_visual_kind_accompanies_visual_id", "card", type_="check")
    op.drop_column("card", "visual_kind")
    postgresql.ENUM(name="visual_kind").drop(op.get_bind(), checkfirst=True)
