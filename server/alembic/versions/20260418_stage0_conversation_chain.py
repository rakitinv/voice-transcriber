"""Stage 0: recording_session_id, previous_conversation_id on conversations.

Revision ID: stage0_001
Revises: initial_001
Create Date: 2026-04-18

Идемпотентно: после initial_001 колонки уже могут быть в таблице (create_all по моделям).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import UUID

revision = "stage0_001"
down_revision = "initial_001"
branch_labels = None
depends_on = None


def _conversation_columns(bind) -> set[str]:
    insp = inspect(bind)
    if not insp.has_table("conversations"):
        return set()
    return {c["name"] for c in insp.get_columns("conversations")}


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if not insp.has_table("conversations"):
        raise RuntimeError(
            "Таблица conversations отсутствует: ревизия initial_001 не применена "
            "(в образе, скорее всего, старые файлы alembic/versions). "
            "Пересоберите образы: docker compose build migrate api"
        )
    cols = _conversation_columns(bind)
    if "recording_session_id" in cols and "previous_conversation_id" in cols:
        return
    if "recording_session_id" not in cols:
        op.add_column(
            "conversations",
            sa.Column("recording_session_id", UUID(as_uuid=True), nullable=True),
        )
    if "previous_conversation_id" not in cols:
        op.add_column(
            "conversations",
            sa.Column("previous_conversation_id", UUID(as_uuid=True), nullable=True),
        )
    fk_names = {fk["name"] for fk in inspect(bind).get_foreign_keys("conversations")}
    if "fk_conversations_previous_conversation_id" not in fk_names:
        op.create_foreign_key(
            "fk_conversations_previous_conversation_id",
            "conversations",
            "conversations",
            ["previous_conversation_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.execute(
        "UPDATE conversations SET recording_session_id = id "
        "WHERE recording_session_id IS NULL"
    )
    op.alter_column("conversations", "recording_session_id", nullable=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if not insp.has_table("conversations"):
        return
    fk_names = {fk["name"] for fk in insp.get_foreign_keys("conversations")}
    if "fk_conversations_previous_conversation_id" in fk_names:
        op.drop_constraint(
            "fk_conversations_previous_conversation_id",
            "conversations",
            type_="foreignkey",
        )
    cols = _conversation_columns(bind)
    if "previous_conversation_id" in cols:
        op.drop_column("conversations", "previous_conversation_id")
    if "recording_session_id" in cols:
        op.drop_column("conversations", "recording_session_id")
