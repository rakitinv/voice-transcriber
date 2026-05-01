"""conversations.audio_uploaded_at — время последней загрузки аудио.

Revision ID: phase_audio_uploaded_005
Revises: phase_c1_004
Create Date: 2026-04-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "phase_audio_uploaded_005"
down_revision = "phase_c1_004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if not insp.has_table("conversations"):
        return
    cols = {c["name"] for c in insp.get_columns("conversations")}
    if "audio_uploaded_at" in cols:
        return
    op.add_column(
        "conversations",
        sa.Column("audio_uploaded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE conversations SET audio_uploaded_at = created_at "
        "WHERE audio_uploaded_at IS NULL"
    )


def downgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if not insp.has_table("conversations"):
        return
    cols = {c["name"] for c in insp.get_columns("conversations")}
    if "audio_uploaded_at" not in cols:
        return
    op.drop_column("conversations", "audio_uploaded_at")
