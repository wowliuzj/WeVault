"""create admins

Revision ID: 20260622_0013
Revises: 20260617_0012
Create Date: 2026-06-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260622_0013"
down_revision: str | None = "20260617_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

admin_status = postgresql.ENUM(
    "active",
    "restricted",
    "disabled",
    name="admin_status",
    create_type=False,
)


def upgrade() -> None:
    admin_status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "admins",
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=80), nullable=True),
        sa.Column("status", admin_status, nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admins")),
    )
    op.create_index(op.f("ix_admins_email"), "admins", ["email"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_admins_email"), table_name="admins")
    op.drop_table("admins")
    admin_status.drop(op.get_bind(), checkfirst=True)
