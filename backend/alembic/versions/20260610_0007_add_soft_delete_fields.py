"""add soft delete fields

Revision ID: 20260610_0007
Revises: 20260610_0006
Create Date: 2026-06-11
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260610_0007"
down_revision: str | None = "20260610_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("articles", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f("ix_articles_deleted_at"), "articles", ["deleted_at"], unique=False)
    op.add_column(
        "wechat_sources",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        op.f("ix_wechat_sources_deleted_at"),
        "wechat_sources",
        ["deleted_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_wechat_sources_deleted_at"), table_name="wechat_sources")
    op.drop_column("wechat_sources", "deleted_at")
    op.drop_index(op.f("ix_articles_deleted_at"), table_name="articles")
    op.drop_column("articles", "deleted_at")
