"""pipeline_events + ASR parallel chunk progress columns (ADMIN_OPS_SPRINT8).

Revision ID: pipeline_events_sprint8_012
Revises: auth_signin_events_011
Create Date: 2026-05-14

Идемпотентно: колонки и таблица уже могут существовать после initial_001 (create_all).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision = "pipeline_events_sprint8_012"
down_revision = "auth_signin_events_011"
branch_labels = None
depends_on = None


def _column_names(bind, table: str) -> set[str]:
    insp = inspect(bind)
    if not insp.has_table(table):
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def _has_index(bind, table: str, name: str) -> bool:
    return any(idx.get("name") == name for idx in inspect(bind).get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    tcols = _column_names(bind, "transcripts")
    if "asr_chunk_total" not in tcols:
        op.add_column(
            "transcripts",
            sa.Column("asr_chunk_total", sa.Integer(), nullable=True),
        )
    if "asr_chunk_completed" not in tcols:
        op.add_column(
            "transcripts",
            sa.Column("asr_chunk_completed", sa.Integer(), nullable=True),
        )

    if not insp.has_table("pipeline_events"):
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

    if insp.has_table("pipeline_events"):
        for idx_name, cols in (
            ("ix_pipeline_events_conversation_id_created_at", ["conversation_id", "created_at"]),
            ("ix_pipeline_events_created_at", ["created_at"]),
            ("ix_pipeline_events_event_type_created_at", ["event_type", "created_at"]),
        ):
            if not _has_index(bind, "pipeline_events", idx_name):
                op.create_index(idx_name, "pipeline_events", cols, unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if insp.has_table("pipeline_events"):
        for idx_name in (
            "ix_pipeline_events_event_type_created_at",
            "ix_pipeline_events_created_at",
            "ix_pipeline_events_conversation_id_created_at",
        ):
            if _has_index(bind, "pipeline_events", idx_name):
                op.drop_index(idx_name, table_name="pipeline_events")
        op.drop_table("pipeline_events")
    tcols = _column_names(bind, "transcripts")
    if "asr_chunk_completed" in tcols:
        op.drop_column("transcripts", "asr_chunk_completed")
    if "asr_chunk_total" in tcols:
        op.drop_column("transcripts", "asr_chunk_total")
