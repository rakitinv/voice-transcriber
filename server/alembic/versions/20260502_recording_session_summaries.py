"""recording_session_summaries for §7.6 chain LLM summary.

Revision ID: phase_c7_session_summary_008
Revises: c6_api_keys_001
Create Date: 2026-05-02

Идемпотентно: таблица уже может существовать после initial_001 (create_all).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision = "phase_c7_session_summary_008"
down_revision = "c6_api_keys_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if inspect(bind).has_table("recording_session_summaries"):
        return
    op.create_table(
        "recording_session_summaries",
        sa.Column("recording_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("summary_md", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("recording_session_id"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if not inspect(bind).has_table("recording_session_summaries"):
        return
    op.drop_table("recording_session_summaries")
