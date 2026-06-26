"""auth_signin_events — product login audit (ADMIN_OPS_SPRINT6 Epic S).

Revision ID: auth_signin_events_011
Revises: admin_audit_events_010
Create Date: 2026-05-14

Идемпотентно: таблица уже может существовать после initial_001 (create_all).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision = "auth_signin_events_011"
down_revision = "admin_audit_events_010"
branch_labels = None
depends_on = None


def _has_index(bind, table: str, name: str) -> bool:
    return any(idx.get("name") == name for idx in inspect(bind).get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if not insp.has_table("auth_signin_events"):
        op.create_table(
            "auth_signin_events",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("outcome", sa.String(length=16), nullable=False),
            sa.Column("channel", sa.String(length=32), nullable=False),
            sa.Column("reason_code", sa.String(length=64), nullable=True),
            sa.Column("provider", sa.String(length=32), nullable=True),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("client_fingerprint", sa.String(length=64), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
    if insp.has_table("auth_signin_events") and not _has_index(
        bind, "auth_signin_events", "ix_auth_signin_events_created_at"
    ):
        op.create_index(
            "ix_auth_signin_events_created_at",
            "auth_signin_events",
            ["created_at"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    if not inspect(bind).has_table("auth_signin_events"):
        return
    op.drop_index("ix_auth_signin_events_created_at", table_name="auth_signin_events")
    op.drop_table("auth_signin_events")
