"""Initial schema: create all ORM tables (empty database).

Revision ID: initial_001
Revises:
Create Date: 2026-04-18
"""

from __future__ import annotations

from alembic import op

from app.models import Base

revision = "initial_001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
