"""Transcript versioning + active pointer.

Revision ID: phase_c1_004
Revises: phase_audio_ext_003
Create Date: 2026-04-20

Идемпотентно: после initial_001 (create_all по моделям) колонки и ограничения уже могут существовать.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "phase_c1_004"
down_revision = "phase_audio_ext_003"
branch_labels = None
depends_on = None


def _column_names(bind, table: str) -> set[str]:
    insp = inspect(bind)
    if not insp.has_table(table):
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def _has_unique_constraint(bind, table: str, name: str) -> bool:
    insp = inspect(bind)
    return any(uc.get("name") == name for uc in insp.get_unique_constraints(table))


def _has_index(bind, table: str, name: str) -> bool:
    insp = inspect(bind)
    return any(idx.get("name") == name for idx in insp.get_indexes(table))


def _has_foreign_key(bind, table: str, name: str) -> bool:
    insp = inspect(bind)
    return any(fk.get("name") == name for fk in insp.get_foreign_keys(table))


def upgrade() -> None:
    bind = op.get_bind()
    tcols = _column_names(bind, "transcripts")
    if not tcols:
        raise RuntimeError(
            "Таблица transcripts отсутствует: сначала должна примениться initial_001. "
            "Пересоберите образы: docker compose build migrate api"
        )

    versioning_cols = ("revision", "kind", "status", "meta")
    need_transcript_alter = any(c not in tcols for c in versioning_cols)

    if need_transcript_alter:
        with op.batch_alter_table("transcripts") as batch:
            if "revision" not in tcols:
                batch.add_column(sa.Column("revision", sa.Integer(), nullable=True))
            if "kind" not in tcols:
                batch.add_column(sa.Column("kind", sa.String(length=64), nullable=True))
            if "status" not in tcols:
                batch.add_column(sa.Column("status", sa.String(length=16), nullable=True))
            if "meta" not in tcols:
                batch.add_column(sa.Column("meta", postgresql.JSONB(), nullable=True))

        op.execute("UPDATE transcripts SET revision = 1 WHERE revision IS NULL")
        op.execute("UPDATE transcripts SET kind = 'asr' WHERE kind IS NULL")
        op.execute("UPDATE transcripts SET status = 'success' WHERE status IS NULL")

        with op.batch_alter_table("transcripts") as batch:
            batch.alter_column("revision", existing_type=sa.Integer(), nullable=False)
            batch.alter_column("kind", existing_type=sa.String(length=64), nullable=False)
            batch.alter_column("status", existing_type=sa.String(length=16), nullable=False)

    if not _has_unique_constraint(bind, "transcripts", "uq_transcripts_conversation_revision"):
        with op.batch_alter_table("transcripts") as batch:
            batch.create_unique_constraint(
                "uq_transcripts_conversation_revision", ["conversation_id", "revision"]
            )

    if not _has_index(bind, "transcripts", "ix_transcripts_conversation_status_revision"):
        with op.batch_alter_table("transcripts") as batch:
            batch.create_index(
                "ix_transcripts_conversation_status_revision",
                ["conversation_id", "status", "revision"],
            )

    ccols = _column_names(bind, "conversations")
    if "active_transcript_id" not in ccols:
        with op.batch_alter_table("conversations") as batch:
            batch.add_column(sa.Column("active_transcript_id", sa.Integer(), nullable=True))

    if not _has_foreign_key(bind, "conversations", "fk_conversations_active_transcript_id"):
        with op.batch_alter_table("conversations") as batch:
            batch.create_foreign_key(
                "fk_conversations_active_transcript_id",
                "transcripts",
                ["active_transcript_id"],
                ["id"],
                ondelete="SET NULL",
            )

    op.execute(
        """
        UPDATE conversations c
        SET active_transcript_id = t.id
        FROM (
          SELECT conversation_id, MAX(id) AS id
          FROM transcripts
          GROUP BY conversation_id
        ) t
        WHERE c.id = t.conversation_id AND c.active_transcript_id IS NULL
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if _has_foreign_key(bind, "conversations", "fk_conversations_active_transcript_id"):
        with op.batch_alter_table("conversations") as batch:
            batch.drop_constraint("fk_conversations_active_transcript_id", type_="foreignkey")
    ccols = _column_names(bind, "conversations")
    if "active_transcript_id" in ccols:
        with op.batch_alter_table("conversations") as batch:
            batch.drop_column("active_transcript_id")

    if _has_index(bind, "transcripts", "ix_transcripts_conversation_status_revision"):
        with op.batch_alter_table("transcripts") as batch:
            batch.drop_index("ix_transcripts_conversation_status_revision")
    if _has_unique_constraint(bind, "transcripts", "uq_transcripts_conversation_revision"):
        with op.batch_alter_table("transcripts") as batch:
            batch.drop_constraint("uq_transcripts_conversation_revision", type_="unique")

    tcols = _column_names(bind, "transcripts")
    with op.batch_alter_table("transcripts") as batch:
        if "meta" in tcols:
            batch.drop_column("meta")
        if "status" in tcols:
            batch.drop_column("status")
        if "kind" in tcols:
            batch.drop_column("kind")
        if "revision" in tcols:
            batch.drop_column("revision")
