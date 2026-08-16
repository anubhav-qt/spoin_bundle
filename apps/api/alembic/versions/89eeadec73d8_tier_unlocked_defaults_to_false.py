"""tier_unlocked defaults to false

`user_topic_progress.tier_unlocked` is the QUIZ unlock latch — "this user has
covered 80% of every subtopic in that tier" — not "this user may read that tier".
Which tier they are reading is `current_difficulty`.

The original default of `[true, false, false]` conflated the two, so a brand-new
user was reported as having a beginner quiz ready before reading a single card.

The column default lives in Python, so there is no schema change here. What needs
fixing is the rows already written under the old default. Only rows that are
*still* untouched are corrected: a genuinely earned unlock is latched and must
never be revoked by a migration, which is the same rule the application obeys.

Revision ID: 89eeadec73d8
Revises: f49f90af49c0
Create Date: 2026-08-15 15:11:13.223880
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "89eeadec73d8"
down_revision: str | None = "f49f90af49c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE user_topic_progress
           SET tier_unlocked = ARRAY[false, false, false]
         WHERE tier_unlocked = ARRAY[true, false, false]
           AND tier_quiz_passed = ARRAY[false, false, false]
           AND mastered_at IS NULL
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE user_topic_progress
           SET tier_unlocked = ARRAY[true, false, false]
         WHERE tier_unlocked = ARRAY[false, false, false]
           AND tier_quiz_passed = ARRAY[false, false, false]
           AND mastered_at IS NULL
        """
    )
