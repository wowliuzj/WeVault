"""add article cover cache

Revision ID: 20260610_0006
Revises: 20260610_0005
Create Date: 2026-06-11
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260610_0006"
down_revision: str | None = "20260610_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("articles", sa.Column("cover_storage_path", sa.Text(), nullable=True))
    op.add_column(
        "articles",
        sa.Column("cover_content_type", sa.String(length=120), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("articles", "cover_content_type")
    op.drop_column("articles", "cover_storage_path")
