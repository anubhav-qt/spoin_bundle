"""a stored vector must name its model

The `embedding_model` stamp arrived with `feded8588fd8`, written by nine call sites.
This makes it structural instead: a row may not carry a vector without naming the model
that produced it, and may not name a model without carrying a vector.

Task 0039 is what the absence costs. A column silently held two incomparable kinds of
vector — hash output and, had the flag ever reached the containers, real ones — every
comparison across them was noise, and no query, log line or test could tell. Nine
correct call sites are discipline; a tenth is one merge away. CLAUDE.md: a hard rule
gets enforced twice, never documented once (ADR-0097).

Written by hand because alembic does not autogenerate `CheckConstraint`s — the
declarations in `__table_args__` produce no diff, so this file is the only thing that
puts them in the database.

Revision ID: b9876ddc6238
Revises: feded8588fd8
Create Date: 2026-09-05 10:34:00.943026
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "b9876ddc6238"
down_revision: str | None = "feded8588fd8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: table, vector column.
_VECTORS = [
    ("card", "content_embedding"),
    ("question", "embedding"),
    ("topic", "embedding"),
]


def upgrade() -> None:
    for table, column in _VECTORS:
        op.create_check_constraint(
            "embedding_names_its_model",
            table,
            f"({column} IS NULL) = (embedding_model IS NULL)",
        )


def downgrade() -> None:
    for table, _column in reversed(_VECTORS):
        # The RENDERED name: `create_check_constraint` runs the short name through the
        # metadata's `ck_%(table_name)s_%(constraint_name)s` convention, and dropping
        # asks the database for what it actually stored.
        op.drop_constraint(f"ck_{table}_embedding_names_its_model", table, type_="check")
