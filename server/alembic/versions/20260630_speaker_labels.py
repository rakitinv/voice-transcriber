"""conversations.speaker_labels + speaker_identification_status (C1.4).

Revision ID: speaker_labels_c14_013
Revises: pipeline_events_sprint8_012
Create Date: 2026-06-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision = "speaker_labels_c14_013"
down_revision = "pipeline_events_sprint8_012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if not insp.has_table("conversations"):
        return
    cols = {c["name"] for c in insp.get_columns("conversations")}
    if "speaker_labels" not in cols:
        op.add_column(
            "conversations",
            sa.Column("speaker_labels", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        )
    if "speaker_identification_status" not in cols:
        op.add_column(
            "conversations",
            sa.Column("speaker_identification_status", sa.String(length=16), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if not insp.has_table("conversations"):
        return
    cols = {c["name"] for c in insp.get_columns("conversations")}
    if "speaker_identification_status" in cols:
        op.drop_column("conversations", "speaker_identification_status")
    if "speaker_labels" in cols:
        op.drop_column("conversations", "speaker_labels")
