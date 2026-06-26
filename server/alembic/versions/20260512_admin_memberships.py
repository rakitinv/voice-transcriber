"""admin_memberships for Ops console (ADMIN_OPS_CONSOLE).

Optional bootstrap when running migrate (same env as compose `migrate` service):
- VT_ADMIN_BOOTSTRAP_USER_ID — UUID of an existing user
- VT_ADMIN_BOOTSTRAP_EMAIL — email of an existing user (case-insensitive)

Revision ID: admin_memberships_009
Revises: phase_c7_session_summary_008
Create Date: 2026-05-12
"""

from __future__ import annotations

import json
import os
import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision = "admin_memberships_009"
down_revision = "phase_c7_session_summary_008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if not inspect(bind).has_table("admin_memberships"):
        op.create_table(
            "admin_memberships",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column(
                "roles",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'[\"admin\"]'::jsonb"),
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", name="uq_admin_memberships_user_id"),
        )

    conn = op.get_bind()
    user_id: uuid.UUID | None = None
    raw_uid = (os.environ.get("VT_ADMIN_BOOTSTRAP_USER_ID") or "").strip()
    if raw_uid:
        try:
            candidate = uuid.UUID(raw_uid)
        except ValueError:
            candidate = None
        if candidate is not None:
            row = conn.execute(
                sa.text("SELECT id FROM users WHERE id = CAST(:id AS uuid)"),
                {"id": str(candidate)},
            ).fetchone()
            if row is not None:
                user_id = row[0] if isinstance(row[0], uuid.UUID) else uuid.UUID(str(row[0]))

    if user_id is None:
        email = (os.environ.get("VT_ADMIN_BOOTSTRAP_EMAIL") or "").strip()
        if email:
            row = conn.execute(
                sa.text("SELECT id FROM users WHERE lower(email) = lower(:email)"),
                {"email": email},
            ).fetchone()
            if row is not None:
                user_id = row[0] if isinstance(row[0], uuid.UUID) else uuid.UUID(str(row[0]))

    if user_id is not None:
        roles_json = json.dumps(["admin"])
        conn.execute(
            sa.text(
                "INSERT INTO admin_memberships (id, user_id, roles, created_at) "
                "VALUES (gen_random_uuid(), CAST(:uid AS uuid), CAST(:roles AS jsonb), now()) "
                "ON CONFLICT (user_id) DO NOTHING"
            ),
            {"uid": str(user_id), "roles": roles_json},
        )


def downgrade() -> None:
    bind = op.get_bind()
    if not inspect(bind).has_table("admin_memberships"):
        return
    op.drop_table("admin_memberships")
