"""topic.curriculum_corpus_version

The deterministic projection of an authored curriculum
(docs/architecture/authored-curriculum.md) stamps the corpus version it projected
against, so staleness -- "the corpus moved under this curriculum" -- is computable
without re-reading the file. `topic.curriculum_generated_at` keeps its column and gains
a meaning: "a curriculum was projected", not "we generated one" (the generated path is
deleted with ADR-0007's `generate_curriculum`).

Nullable, no backfill: pre-projection topics simply have no version, which is the
honest value.

Revision ID: c1d2e3f4a5b6
Revises: b9876ddc6238
Create Date: 2026-09-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c1d2e3f4a5b6"
down_revision: str | None = "b9876ddc6238"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "topic",
        sa.Column("curriculum_corpus_version", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("topic", "curriculum_corpus_version")
