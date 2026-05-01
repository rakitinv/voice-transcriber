"""Transcript versioning + active pointer.

Revision ID: phase_c1_004
Revises: phase_audio_ext_003
Create Date: 2026-04-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# Revision identifiers, used by Alembic.
revision = "phase_c1_004"
down_revision = "phase_audio_ext_003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- transcripts: add versioning fields ---
    with op.batch_alter_table("transcripts") as batch:
        batch.add_column(sa.Column("revision", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("kind", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("status", sa.String(length=16), nullable=True))
        batch.add_column(sa.Column("meta", sa.dialects.postgresql.JSONB(), nullable=True))

    # Backfill defaults for existing rows.
    op.execute("UPDATE transcripts SET revision = 1 WHERE revision IS NULL")
    op.execute("UPDATE transcripts SET kind = 'asr' WHERE kind IS NULL")
    op.execute("UPDATE transcripts SET status = 'success' WHERE status IS NULL")

    with op.batch_alter_table("transcripts") as batch:
        batch.alter_column("revision", existing_type=sa.Integer(), nullable=False)
        batch.alter_column("kind", existing_type=sa.String(length=64), nullable=False)
        batch.alter_column("status", existing_type=sa.String(length=16), nullable=False)
        batch.create_unique_constraint(
            "uq_transcripts_conversation_revision", ["conversation_id", "revision"]
        )

        batch.create_index(
            "ix_transcripts_conversation_status_revision",
            ["conversation_id", "status", "revision"],
        )

    # --- conversations: add active_transcript_id ---
    with op.batch_alter_table("conversations") as batch:
        batch.add_column(sa.Column("active_transcript_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_conversations_active_transcript_id",
            "transcripts",
            ["active_transcript_id"],
            ["id"],
            ondelete="SET NULL",
        )

    # Backfill: set active_transcript_id to the (only) existing transcript if present.
    # If multiple transcripts already exist (unexpected in current code), pick the latest id.
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
    with op.batch_alter_table("conversations") as batch:
        batch.drop_constraint("fk_conversations_active_transcript_id", type_="foreignkey")
        batch.drop_column("active_transcript_id")

    with op.batch_alter_table("transcripts") as batch:
        batch.drop_index("ix_transcripts_conversation_status_revision")
        batch.drop_constraint("uq_transcripts_conversation_revision", type_="unique")
        batch.drop_column("meta")
        batch.drop_column("status")
        batch.drop_column("kind")
        batch.drop_column("revision")

