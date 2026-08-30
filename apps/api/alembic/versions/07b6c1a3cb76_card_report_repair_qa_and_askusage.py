"""card_report_repair_qa_and_askusage

ADR-0076 (report a card + operator repair lane) and ADR-0077 (AskAI):

- `card_report`   -- a reader flagging a live card as structurally broken
- `card_repair`   -- the operator's fix/remake instruction + audit trail
- `generation_job.kind` / `.card_id` -- a second job kind ('repair') alongside
  'generate', coalesced on `card_id` instead of `topic_id`
- `card_status` gains 'retired' -- an operator-pulled card
- `card_qa`      -- cached AskAI exchanges
- `ask_usage`    -- per-user per-UTC-day AskAI question counter

Revision ID: 07b6c1a3cb76
Revises: f0a1c2b3d4e5
Create Date: 2026-08-30 17:32:09.143198
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "07b6c1a3cb76"
down_revision: str | None = "f0a1c2b3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_card_report_reason = sa.Enum(
    "art", "diagram", "code_block", "formatting", "other", name="card_report_reason"
)
_repair_mode = sa.Enum("fix", "remake", name="repair_mode")
_repair_status = sa.Enum("pending", "running", "done", "failed", name="repair_status")


def upgrade() -> None:
    # -- card_status gains 'retired' -------------------------------------------
    # ALTER TYPE ... ADD VALUE cannot run inside the migration's transaction.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE card_status ADD VALUE IF NOT EXISTS 'retired'")

    # -- report / repair ----------------------------------------------------
    op.create_table(
        "card_report",
        sa.Column("card_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("reason", _card_report_reason, nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["card_id"], ["card.id"], name=op.f("fk_card_report_card_id_card"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.id"],
            name=op.f("fk_card_report_user_id_app_user"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_card_report")),
        sa.UniqueConstraint("card_id", "user_id", name="uq_card_report_card_user"),
    )
    op.create_index(
        "ix_card_report_unresolved",
        "card_report",
        ["card_id"],
        unique=False,
        postgresql_where=sa.text("resolved_at IS NULL"),
    )

    op.create_table(
        "card_repair",
        sa.Column("card_id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=True),
        sa.Column("mode", _repair_mode, nullable=False),
        sa.Column("guidance", sa.Text(), nullable=True),
        sa.Column("source_image", sa.LargeBinary(), nullable=True),
        sa.Column("status", _repair_status, nullable=False),
        sa.Column("result_card_id", sa.UUID(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["card_id"], ["card.id"], name=op.f("fk_card_repair_card_id_card"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["generation_job.id"],
            name=op.f("fk_card_repair_job_id_generation_job"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["result_card_id"],
            ["card.id"],
            name=op.f("fk_card_repair_result_card_id_card"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_card_repair")),
    )
    op.create_index("ix_card_repair_status", "card_repair", ["status"], unique=False)

    # -- generation_job: second kind, coalesced on card_id -----------------
    op.add_column(
        "generation_job",
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="generate"),
    )
    op.add_column("generation_job", sa.Column("card_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_generation_job_card_id_card"),
        "generation_job",
        "card",
        ["card_id"],
        ["id"],
        ondelete="CASCADE",
    )
    # The old topic coalescing lock did not scope to kind; it must now, so a
    # repair job cannot block a generate job for the same topic.
    op.drop_index("uq_generation_job_topic_pending", table_name="generation_job")
    op.create_index(
        "uq_generation_job_topic_pending",
        "generation_job",
        ["topic_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'generate' AND status IN ('pending', 'running')"),
    )
    op.create_index(
        "uq_generation_job_card_pending",
        "generation_job",
        ["card_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'repair' AND status IN ('pending', 'running')"),
    )

    # -- AskAI ------------------------------------------------------------
    op.create_table(
        "card_qa",
        sa.Column("card_id", sa.UUID(), nullable=False),
        sa.Column("question_norm", sa.String(length=500), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("on_topic", sa.Boolean(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["card_id"], ["card.id"], name=op.f("fk_card_qa_card_id_card"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_card_qa")),
        sa.UniqueConstraint("card_id", "question_norm", name="uq_card_qa_card_question"),
    )
    op.create_table(
        "ask_usage",
        sa.Column("day", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("questions_spent", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.id"],
            name=op.f("fk_ask_usage_user_id_app_user"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("day", "user_id", name=op.f("pk_ask_usage")),
    )


def downgrade() -> None:
    op.drop_table("ask_usage")
    op.drop_table("card_qa")

    op.drop_index("uq_generation_job_card_pending", table_name="generation_job")
    op.drop_index("uq_generation_job_topic_pending", table_name="generation_job")
    op.create_index(
        "uq_generation_job_topic_pending",
        "generation_job",
        ["topic_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'running')"),
    )
    op.drop_constraint(op.f("fk_generation_job_card_id_card"), "generation_job", type_="foreignkey")
    op.drop_column("generation_job", "card_id")
    op.drop_column("generation_job", "kind")

    op.drop_index("ix_card_repair_status", table_name="card_repair")
    op.drop_table("card_repair")
    op.drop_index("ix_card_report_unresolved", table_name="card_report")
    op.drop_table("card_report")

    _repair_status.drop(op.get_bind(), checkfirst=True)
    _repair_mode.drop(op.get_bind(), checkfirst=True)
    _card_report_reason.drop(op.get_bind(), checkfirst=True)
    # 'retired' stays in card_status -- PostgreSQL cannot drop one enum value.
