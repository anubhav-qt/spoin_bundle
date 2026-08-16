"""initial schema

Revision ID: f49f90af49c0
Revises: 
Create Date: 2026-08-15 14:36:17.542331
"""

from __future__ import annotations

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'f49f90af49c0'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # pgvector lives in the same Postgres as everything else (ADR-0003: one
    # store for relational data *and* embeddings, no separate vector DB).
    # Created here rather than by hand so a fresh clone needs no setup step.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table('app_user',
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('display_name', sa.String(length=80), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_app_user')),
    sa.UniqueConstraint('email', name=op.f('uq_app_user_email'))
    )
    op.create_table('quota_ledger',
    sa.Column('day', sa.DateTime(timezone=True), nullable=False),
    sa.Column('backend', sa.String(length=32), nullable=False),
    sa.Column('requests_spent', sa.Integer(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('day', 'backend', name=op.f('pk_quota_ledger'))
    )
    op.create_table('topic',
    sa.Column('slug', sa.String(length=120), nullable=False),
    sa.Column('canonical_name', sa.String(length=120), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('embedding', pgvector.sqlalchemy.vector.VECTOR(dim=384), nullable=True),
    sa.Column('is_seeded', sa.Boolean(), nullable=False),
    sa.Column('is_survey', sa.Boolean(), nullable=False),
    sa.Column('curriculum_generated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('subscriber_count', sa.Integer(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_topic')),
    sa.UniqueConstraint('slug', name=op.f('uq_topic_slug'))
    )
    op.create_table('feed_plan',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('topic_order', postgresql.ARRAY(sa.UUID()), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('filter_key', sa.String(length=64), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['app_user.id'], name=op.f('fk_feed_plan_user_id_app_user'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_feed_plan')),
    sa.UniqueConstraint('user_id', name=op.f('uq_feed_plan_user_id'))
    )
    op.create_table('feed_slate',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('topic_id', sa.UUID(), nullable=False),
    sa.Column('card_ids', postgresql.ARRAY(sa.UUID()), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('degraded', sa.Boolean(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['topic_id'], ['topic.id'], name=op.f('fk_feed_slate_topic_id_topic'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['app_user.id'], name=op.f('fk_feed_slate_user_id_app_user'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_feed_slate')),
    sa.UniqueConstraint('user_id', 'topic_id', name=op.f('uq_feed_slate_user_id_topic_id'))
    )
    op.create_table('quiz_attempt',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('topic_id', sa.UUID(), nullable=False),
    sa.Column('difficulty', sa.Enum('beginner', 'intermediate', 'advanced', name='difficulty'), nullable=False),
    sa.Column('kind', sa.Enum('placement', 'promotion', 'mastery', name='quiz_kind'), nullable=False),
    sa.Column('score', sa.Float(), nullable=True),
    sa.Column('passed', sa.Boolean(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('graded_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['topic_id'], ['topic.id'], name=op.f('fk_quiz_attempt_topic_id_topic'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['app_user.id'], name=op.f('fk_quiz_attempt_user_id_app_user'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_quiz_attempt'))
    )
    op.create_table('subtopic',
    sa.Column('topic_id', sa.UUID(), nullable=False),
    sa.Column('difficulty', sa.Enum('beginner', 'intermediate', 'advanced', name='difficulty'), nullable=False),
    sa.Column('title', sa.String(length=160), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('target_cards', sa.Integer(), nullable=False),
    sa.Column('min_cards', sa.Integer(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('min_cards <= target_cards', name=op.f('ck_subtopic_min_within_target')),
    sa.CheckConstraint('target_cards BETWEEN 5 AND 25', name=op.f('ck_subtopic_target_cards_band')),
    sa.ForeignKeyConstraint(['topic_id'], ['topic.id'], name=op.f('fk_subtopic_topic_id_topic'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_subtopic'))
    )
    op.create_index('ix_subtopic_topic_id_difficulty', 'subtopic', ['topic_id', 'difficulty'], unique=False)
    op.create_table('topic_alias',
    sa.Column('normalized_text', sa.String(length=200), nullable=False),
    sa.Column('raw_text', sa.String(length=200), nullable=False),
    sa.Column('topic_id', sa.UUID(), nullable=False),
    sa.Column('decided_by', sa.String(length=20), nullable=False),
    sa.Column('similarity', sa.Float(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['topic_id'], ['topic.id'], name=op.f('fk_topic_alias_topic_id_topic'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_topic_alias')),
    sa.UniqueConstraint('normalized_text', name='uq_topic_alias_normalized_text')
    )
    op.create_table('topic_edge',
    sa.Column('from_topic_id', sa.UUID(), nullable=False),
    sa.Column('to_topic_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.Enum('deep_dive', name='topic_edge_kind'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('from_topic_id <> to_topic_id', name=op.f('ck_topic_edge_no_self_edge')),
    sa.ForeignKeyConstraint(['from_topic_id'], ['topic.id'], name=op.f('fk_topic_edge_from_topic_id_topic'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['to_topic_id'], ['topic.id'], name=op.f('fk_topic_edge_to_topic_id_topic'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_topic_edge')),
    sa.UniqueConstraint('from_topic_id', 'to_topic_id', 'kind', name=op.f('uq_topic_edge_from_topic_id_to_topic_id_kind'))
    )
    op.create_table('user_seen_bitmap',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('topic_id', sa.UUID(), nullable=False),
    sa.Column('bits', sa.LargeBinary(), nullable=False),
    sa.Column('rebuilt_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['topic_id'], ['topic.id'], name=op.f('fk_user_seen_bitmap_topic_id_topic'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['app_user.id'], name=op.f('fk_user_seen_bitmap_user_id_app_user'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'topic_id', name=op.f('pk_user_seen_bitmap'))
    )
    op.create_table('user_topic',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('topic_id', sa.UUID(), nullable=False),
    sa.Column('display_name', sa.String(length=120), nullable=False),
    sa.Column('is_custom', sa.Boolean(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['topic_id'], ['topic.id'], name=op.f('fk_user_topic_topic_id_topic'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['app_user.id'], name=op.f('fk_user_topic_user_id_app_user'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_user_topic')),
    sa.UniqueConstraint('user_id', 'topic_id', name=op.f('uq_user_topic_user_id_topic_id'))
    )
    op.create_table('user_topic_affinity',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('topic_id', sa.UUID(), nullable=False),
    sa.Column('affinity', sa.Float(), nullable=False),
    sa.Column('recomputed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['topic_id'], ['topic.id'], name=op.f('fk_user_topic_affinity_topic_id_topic'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['app_user.id'], name=op.f('fk_user_topic_affinity_user_id_app_user'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'topic_id', name=op.f('pk_user_topic_affinity'))
    )
    op.create_table('user_topic_cycle',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('topic_id', sa.UUID(), nullable=False),
    sa.Column('difficulty', sa.Enum('beginner', 'intermediate', 'advanced', name='difficulty'), nullable=False),
    sa.Column('cycle', sa.Integer(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['topic_id'], ['topic.id'], name=op.f('fk_user_topic_cycle_topic_id_topic'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['app_user.id'], name=op.f('fk_user_topic_cycle_user_id_app_user'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'topic_id', 'difficulty', name=op.f('pk_user_topic_cycle'))
    )
    op.create_table('user_topic_progress',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('topic_id', sa.UUID(), nullable=False),
    sa.Column('current_difficulty', sa.Enum('beginner', 'intermediate', 'advanced', name='difficulty'), nullable=False),
    sa.Column('tier_unlocked', postgresql.ARRAY(sa.Boolean()), nullable=False),
    sa.Column('tier_content_complete', postgresql.ARRAY(sa.Boolean()), nullable=False),
    sa.Column('tier_quiz_passed', postgresql.ARRAY(sa.Boolean()), nullable=False),
    sa.Column('mastered_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revisit_mode', sa.Boolean(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['topic_id'], ['topic.id'], name=op.f('fk_user_topic_progress_topic_id_topic'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['app_user.id'], name=op.f('fk_user_topic_progress_user_id_app_user'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'topic_id', name=op.f('pk_user_topic_progress'))
    )
    op.create_table('card',
    sa.Column('family_id', sa.UUID(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('status', sa.Enum('draft', 'active', 'rejected', 'superseded', name='card_status'), nullable=False),
    sa.Column('topic_id', sa.UUID(), nullable=False),
    sa.Column('subtopic_id', sa.UUID(), nullable=False),
    sa.Column('difficulty', sa.Enum('beginner', 'intermediate', 'advanced', name='difficulty'), nullable=False),
    sa.Column('judged_difficulty', sa.Enum('beginner', 'intermediate', 'advanced', name='difficulty'), nullable=True),
    sa.Column('title', sa.String(length=120), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('source', sa.Enum('generated', 'authored', name='card_source'), nullable=False),
    sa.Column('author_id', sa.UUID(), nullable=True),
    sa.Column('content_embedding', pgvector.sqlalchemy.vector.VECTOR(dim=384), nullable=True),
    sa.Column('gen_meta', postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), 'sqlite'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('version >= 1', name=op.f('ck_card_version_positive')),
    sa.ForeignKeyConstraint(['author_id'], ['app_user.id'], name=op.f('fk_card_author_id_app_user'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['subtopic_id'], ['subtopic.id'], name=op.f('fk_card_subtopic_id_subtopic'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['topic_id'], ['topic.id'], name=op.f('fk_card_topic_id_topic'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_card')),
    sa.UniqueConstraint('family_id', 'version', name=op.f('uq_card_family_id_version'))
    )
    op.create_index('ix_card_subtopic_id_status_difficulty', 'card', ['subtopic_id', 'status', 'difficulty'], unique=False)
    op.create_index('ix_card_topic_id_status_difficulty', 'card', ['topic_id', 'status', 'difficulty'], unique=False)
    op.create_index('uq_card_family_id_active', 'card', ['family_id'], unique=True, postgresql_where=sa.text("status = 'active'"))
    op.create_table('generation_job',
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('topic_id', sa.UUID(), nullable=False),
    sa.Column('subtopic_id', sa.UUID(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('priority', sa.Integer(), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['subtopic_id'], ['subtopic.id'], name=op.f('fk_generation_job_subtopic_id_subtopic'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['topic_id'], ['topic.id'], name=op.f('fk_generation_job_topic_id_topic'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_generation_job'))
    )
    op.create_index('ix_generation_job_status_priority', 'generation_job', ['status', 'priority'], unique=False)
    op.create_index('uq_generation_job_subtopic_pending', 'generation_job', ['subtopic_id'], unique=True, postgresql_where=sa.text("status IN ('pending', 'running')"))
    op.create_table('user_subtopic_progress',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('subtopic_id', sa.UUID(), nullable=False),
    sa.Column('seen_count', sa.Integer(), nullable=False),
    sa.Column('total_count', sa.Integer(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['subtopic_id'], ['subtopic.id'], name=op.f('fk_user_subtopic_progress_subtopic_id_subtopic'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['app_user.id'], name=op.f('fk_user_subtopic_progress_user_id_app_user'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'subtopic_id', name=op.f('pk_user_subtopic_progress'))
    )
    op.create_table('card_bookmark',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('card_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['card_id'], ['card.id'], name=op.f('fk_card_bookmark_card_id_card'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['app_user.id'], name=op.f('fk_card_bookmark_user_id_app_user'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'card_id', name=op.f('pk_card_bookmark'))
    )
    op.create_table('card_like',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('card_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['card_id'], ['card.id'], name=op.f('fk_card_like_card_id_card'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['app_user.id'], name=op.f('fk_card_like_user_id_app_user'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'card_id', name=op.f('pk_card_like'))
    )
    op.create_table('card_note',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('card_id', sa.UUID(), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['card_id'], ['card.id'], name=op.f('fk_card_note_card_id_card'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['app_user.id'], name=op.f('fk_card_note_user_id_app_user'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'card_id', name=op.f('pk_card_note'))
    )
    op.create_table('card_stats',
    sa.Column('card_id', sa.UUID(), nullable=False),
    sa.Column('impressions', sa.Integer(), nullable=False),
    sa.Column('expands', sa.Integer(), nullable=False),
    sa.Column('likes', sa.Integer(), nullable=False),
    sa.Column('bookmarks', sa.Integer(), nullable=False),
    sa.Column('explicit_completes', sa.Integer(), nullable=False),
    sa.Column('dwell_completes', sa.Integer(), nullable=False),
    sa.Column('skips', sa.Integer(), nullable=False),
    sa.Column('avg_dwell_ms', sa.Float(), nullable=False),
    sa.Column('quality', sa.Float(), nullable=False),
    sa.Column('recomputed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['card_id'], ['card.id'], name=op.f('fk_card_stats_card_id_card'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('card_id', name=op.f('pk_card_stats'))
    )
    op.create_table('engagement_event',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('card_id', sa.UUID(), nullable=False),
    sa.Column('topic_id', sa.UUID(), nullable=False),
    sa.Column('subtopic_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.Enum('impression', 'expand', 'collapse', 'dwell', 'skip', 'like', 'unlike', 'bookmark', 'unbookmark', 'note', 'share', 'ask_ai', 'explicit_complete', 'dwell_complete', name='engagement_kind'), nullable=False),
    sa.Column('dwell_ms', sa.Integer(), nullable=True),
    sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('client_occurred_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('session_id', sa.UUID(), nullable=True),
    sa.CheckConstraint('dwell_ms IS NULL OR dwell_ms >= 0', name=op.f('ck_engagement_event_dwell_non_negative')),
    sa.ForeignKeyConstraint(['card_id'], ['card.id'], name=op.f('fk_engagement_event_card_id_card'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['app_user.id'], name=op.f('fk_engagement_event_user_id_app_user'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_engagement_event'))
    )
    op.create_index('ix_engagement_event_card_id_kind', 'engagement_event', ['card_id', 'kind'], unique=False)
    op.create_index('ix_engagement_event_user_id_occurred_at', 'engagement_event', ['user_id', 'occurred_at'], unique=False)
    op.create_table('question',
    sa.Column('subtopic_id', sa.UUID(), nullable=False),
    sa.Column('card_id', sa.UUID(), nullable=False),
    sa.Column('difficulty', sa.Enum('beginner', 'intermediate', 'advanced', name='difficulty'), nullable=False),
    sa.Column('kind', sa.Enum('mcq', 'free_text', name='question_kind'), nullable=False),
    sa.Column('stem', sa.Text(), nullable=False),
    sa.Column('options', postgresql.ARRAY(sa.Text()), nullable=True),
    sa.Column('correct_index', sa.Integer(), nullable=True),
    sa.Column('rubric', sa.Text(), nullable=True),
    sa.Column('reference_answer', sa.Text(), nullable=True),
    sa.Column('explanation', sa.Text(), nullable=True),
    sa.Column('status', sa.Enum('draft', 'active', 'rejected', name='question_status'), nullable=False),
    sa.Column('embedding', pgvector.sqlalchemy.vector.VECTOR(dim=384), nullable=True),
    sa.Column('gen_meta', postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), 'sqlite'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(kind = 'mcq' AND options IS NOT NULL AND correct_index IS NOT NULL) OR (kind = 'free_text' AND rubric IS NOT NULL)", name=op.f('ck_question_kind_fields_present')),
    sa.ForeignKeyConstraint(['card_id'], ['card.id'], name=op.f('fk_question_card_id_card'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['subtopic_id'], ['subtopic.id'], name=op.f('fk_question_subtopic_id_subtopic'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_question'))
    )
    op.create_index('ix_question_subtopic_id_status', 'question', ['subtopic_id', 'status'], unique=False)
    op.create_table('user_card_state',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('card_id', sa.UUID(), nullable=False),
    sa.Column('topic_id', sa.UUID(), nullable=False),
    sa.Column('subtopic_id', sa.UUID(), nullable=False),
    sa.Column('state', sa.Enum('unseen', 'deferred', 'seen', name='seen_state'), nullable=False),
    sa.Column('deferred_cycle', sa.Integer(), nullable=True),
    sa.Column('completed_via', sa.Enum('impression', 'expand', 'collapse', 'dwell', 'skip', 'like', 'unlike', 'bookmark', 'unbookmark', 'note', 'share', 'ask_ai', 'explicit_complete', 'dwell_complete', name='engagement_kind'), nullable=True),
    sa.Column('seen_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['card_id'], ['card.id'], name=op.f('fk_user_card_state_card_id_card'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['app_user.id'], name=op.f('fk_user_card_state_user_id_app_user'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'card_id', name=op.f('pk_user_card_state'))
    )
    op.create_index('ix_user_card_state_user_id_topic_id_state', 'user_card_state', ['user_id', 'topic_id', 'state'], unique=False)
    op.create_table('quiz_attempt_question',
    sa.Column('attempt_id', sa.UUID(), nullable=False),
    sa.Column('question_id', sa.UUID(), nullable=False),
    sa.Column('user_answer', sa.Text(), nullable=True),
    sa.Column('correct', sa.Boolean(), nullable=True),
    sa.Column('rubric_level', sa.Integer(), nullable=True),
    sa.Column('justification', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['attempt_id'], ['quiz_attempt.id'], name=op.f('fk_quiz_attempt_question_attempt_id_quiz_attempt'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['question_id'], ['question.id'], name=op.f('fk_quiz_attempt_question_question_id_question'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('attempt_id', 'question_id', name=op.f('pk_quiz_attempt_question'))
    )
    op.create_table('user_question_seen',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('question_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['question_id'], ['question.id'], name=op.f('fk_user_question_seen_question_id_question'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['app_user.id'], name=op.f('fk_user_question_seen_user_id_app_user'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'question_id', name=op.f('pk_user_question_seen'))
    )

def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('user_question_seen')
    op.drop_table('quiz_attempt_question')
    op.drop_index('ix_user_card_state_user_id_topic_id_state', table_name='user_card_state')
    op.drop_table('user_card_state')
    op.drop_index('ix_question_subtopic_id_status', table_name='question')
    op.drop_table('question')
    op.drop_index('ix_engagement_event_user_id_occurred_at', table_name='engagement_event')
    op.drop_index('ix_engagement_event_card_id_kind', table_name='engagement_event')
    op.drop_table('engagement_event')
    op.drop_table('card_stats')
    op.drop_table('card_note')
    op.drop_table('card_like')
    op.drop_table('card_bookmark')
    op.drop_table('user_subtopic_progress')
    op.drop_index('uq_generation_job_subtopic_pending', table_name='generation_job', postgresql_where=sa.text("status IN ('pending', 'running')"))
    op.drop_index('ix_generation_job_status_priority', table_name='generation_job')
    op.drop_table('generation_job')
    op.drop_index('uq_card_family_id_active', table_name='card', postgresql_where=sa.text("status = 'active'"))
    op.drop_index('ix_card_topic_id_status_difficulty', table_name='card')
    op.drop_index('ix_card_subtopic_id_status_difficulty', table_name='card')
    op.drop_table('card')
    op.drop_table('user_topic_progress')
    op.drop_table('user_topic_cycle')
    op.drop_table('user_topic_affinity')
    op.drop_table('user_topic')
    op.drop_table('user_seen_bitmap')
    op.drop_table('topic_edge')
    op.drop_table('topic_alias')
    op.drop_index('ix_subtopic_topic_id_difficulty', table_name='subtopic')
    op.drop_table('subtopic')
    op.drop_table('quiz_attempt')
    op.drop_table('feed_slate')
    op.drop_table('feed_plan')
    op.drop_table('topic')
    op.drop_table('quota_ledger')
    op.drop_table('app_user')
