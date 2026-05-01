"""Phase A: user.preferences, conversation client realtime fields.

Revision ID: phase_a_002
Revises: stage0_001

Идемпотентно: колонки уже могут существовать после initial_001 (create_all по моделям).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import JSONB

revision = "phase_a_002"
down_revision = "stage0_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if not insp.has_table("users"):
        raise RuntimeError(
            "Таблица users отсутствует: сначала должны примениться initial_001 и stage0_001. "
            "Пересоберите образы: docker compose build migrate api"
        )
    ucols = {c["name"] for c in insp.get_columns("users")}
    if "preferences" not in ucols:
        op.add_column("users", sa.Column("preferences", JSONB(), nullable=True))
    if insp.has_table("conversations"):
        ccols = {c["name"] for c in insp.get_columns("conversations")}
        if "client_realtime_mode" not in ccols:
            op.add_column(
                "conversations",
                sa.Column("client_realtime_mode", sa.String(length=32), nullable=True),
            )
        if "client_chunk_ms" not in ccols:
            op.add_column(
                "conversations",
                sa.Column("client_chunk_ms", sa.Integer(), nullable=True),
            )


def downgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if insp.has_table("conversations"):
        ccols = {c["name"] for c in insp.get_columns("conversations")}
        if "client_chunk_ms" in ccols:
            op.drop_column("conversations", "client_chunk_ms")
        if "client_realtime_mode" in ccols:
            op.drop_column("conversations", "client_realtime_mode")
    if insp.has_table("users"):
        ucols = {c["name"] for c in insp.get_columns("users")}
        if "preferences" in ucols:
            op.drop_column("users", "preferences")
