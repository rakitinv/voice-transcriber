"""pipeline_events + ASR parallel chunk progress columns (ADMIN_OPS_SPRINT8).

Revision ID: pipeline_events_sprint8_012
Revises: auth_signin_events_011
Create Date: 2026-05-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "pipeline_events_sprint8_012"
down_revision = "auth_signin_events_011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "transcripts",
        sa.Column("asr_chunk_total", sa.Integer(), nullable=True),
    )
    op.add_column(
        "transcripts",
        sa.Column("asr_chunk_completed", sa.Integer(), nullable=True),
    )

    op.create_table(
        "pipeline_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("transcript_id", sa.Integer(), nullable=True),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["transcript_id"], ["transcripts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_pipeline_events_conversation_id_created_at",
        "pipeline_events",
        ["conversation_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_pipeline_events_created_at",
        "pipeline_events",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_pipeline_events_event_type_created_at",
        "pipeline_events",
        ["event_type", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_pipeline_events_event_type_created_at", table_name="pipeline_events")
    op.drop_index("ix_pipeline_events_created_at", table_name="pipeline_events")
    op.drop_index("ix_pipeline_events_conversation_id_created_at", table_name="pipeline_events")
    op.drop_table("pipeline_events")
    op.drop_column("transcripts", "asr_chunk_completed")
    op.drop_column("transcripts", "asr_chunk_total")
