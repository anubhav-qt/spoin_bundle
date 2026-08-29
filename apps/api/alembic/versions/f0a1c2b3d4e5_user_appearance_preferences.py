"""Server-stored appearance preferences (ADR-0070)

Two new, additive tables. `user_preference` holds the palette, the user's saved
themes, and the font choice — one row per user, created lazily on first write.
`user_font` holds an imported font file (bytes + magic-sniffed format), one row
per import, scoped to its owner.

ADR-0045 kept these client-side; ADR-0070 reverses that for the palette and font
because F4/F5 make them user-authored content that has to follow the user across
devices. `localStorage` stays as a pre-paint cache. `daily_card_goal` and
reduced-motion are unaffected.

Revision ID: f0a1c2b3d4e5
Revises: d1a93f6b25e7
Create Date: 2026-08-30

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f0a1c2b3d4e5"
down_revision: str | None = "d1a93f6b25e7"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "user_preference",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "palette", sa.String(length=64), server_default="notebook", nullable=False
        ),
        sa.Column(
            "custom_palettes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("font", sa.String(length=64), server_default="literata", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.id"],
            name=op.f("fk_user_preference_user_id_app_user"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_user_preference")),
    )

    op.create_table(
        "user_font",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("format", sa.String(length=8), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "format IN ('woff2', 'ttf', 'otf')", name=op.f("ck_user_font_format_valid")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.id"],
            name=op.f("fk_user_font_user_id_app_user"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_font")),
    )
    op.create_index("ix_user_font_user_id", "user_font", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_user_font_user_id", table_name="user_font")
    op.drop_table("user_font")
    op.drop_table("user_preference")
