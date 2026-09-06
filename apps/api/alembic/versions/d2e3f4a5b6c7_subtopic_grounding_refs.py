"""subtopic.grounding_refs: the author declares the scope, the machine ranks within it

An authored curriculum now names, per tier, which corpus sections its cards may be
written from (docs/architecture/authored-curriculum.md). This is where the projection
puts them, and where retrieval reads them.

**Text refs (`<path>#<heading>`), deliberately not resolved chunk ids.** Re-ingesting a
changed document DELETES and rebuilds its chunks, so a `uuid[]` here would rot silently
on the next `make corpus-ingest` and there would be nothing to notice it. A path and a
heading are stable names that resolve late, and a reference that stops resolving shows
up as a scope that came back short -- which the run counts and reports.

Nullable: a subtopic projected before this existed, or one whose curriculum predates the
field, simply has no declared scope and falls back to the open corpus-wide query.

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-09-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d2e3f4a5b6c7"
down_revision: str | None = "c1d2e3f4a5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "subtopic",
        sa.Column("grounding_refs", postgresql.ARRAY(sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("subtopic", "grounding_refs")
