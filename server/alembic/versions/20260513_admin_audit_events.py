"""admin_audit_events for Ops console audit trail (ADMIN_OPS_CONSOLE §8).

Revision ID: admin_audit_events_010
Revises: admin_memberships_009
Create Date: 2026-05-13

Идемпотентно: таблица уже может существовать после initial_001 (create_all).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision = "admin_audit_events_010"
down_revision = "admin_memberships_009"
branch_labels = None
depends_on = None


def _has_index(bind, table: str, name: str) -> bool:
    return any(idx.get("name") == name for idx in inspect(bind).get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if not insp.has_table("admin_audit_events"):
        op.create_table(
            "admin_audit_events",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("admin_user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("action", sa.String(length=128), nullable=False),
            sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("detail", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["admin_user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    if insp.has_table("admin_audit_events") and not _has_index(
        bind, "admin_audit_events", "ix_admin_audit_events_created_at"
    ):
        op.create_index(
            "ix_admin_audit_events_created_at",
            "admin_audit_events",
            ["created_at"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    if not inspect(bind).has_table("admin_audit_events"):
        return
    op.drop_index("ix_admin_audit_events_created_at", table_name="admin_audit_events")
    op.drop_table("admin_audit_events")
