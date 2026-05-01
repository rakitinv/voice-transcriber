"""conversations.audio_object_ext — расширение исходного аудио в S3 (audio.<ext>).

Revision ID: phase_audio_ext_003
Revises: phase_a_002
Create Date: 2026-04-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "phase_audio_ext_003"
down_revision = "phase_a_002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if not insp.has_table("conversations"):
        return
    cols = {c["name"] for c in insp.get_columns("conversations")}
    if "audio_object_ext" in cols:
        return
    op.add_column(
        "conversations",
        sa.Column(
            "audio_object_ext",
            sa.String(length=16),
            nullable=False,
            server_default="webm",
        ),
    )
    op.alter_column("conversations", "audio_object_ext", server_default=None)


def downgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if not insp.has_table("conversations"):
        return
    cols = {c["name"] for c in insp.get_columns("conversations")}
    if "audio_object_ext" not in cols:
        return
    op.drop_column("conversations", "audio_object_ext")
