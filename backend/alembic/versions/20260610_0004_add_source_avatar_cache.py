"""add source avatar cache

Revision ID: 20260610_0004
Revises: 20260610_0003
Create Date: 2026-06-10
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260610_0004"
down_revision: str | None = "20260610_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("wechat_sources", sa.Column("avatar_storage_path", sa.Text(), nullable=True))
    op.add_column(
        "wechat_sources",
        sa.Column("avatar_content_type", sa.String(length=120), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("wechat_sources", "avatar_content_type")
    op.drop_column("wechat_sources", "avatar_storage_path")
