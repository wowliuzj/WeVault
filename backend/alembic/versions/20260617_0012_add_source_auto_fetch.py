"""add source auto fetch schedule fields

Revision ID: 20260617_0012
Revises: 20260615_0011
Create Date: 2026-06-17
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260617_0012"
down_revision: str | None = "20260615_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "wechat_sources",
        sa.Column(
            "auto_fetch_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "wechat_sources",
        sa.Column("auto_fetch_last_scheduled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.alter_column("wechat_sources", "auto_fetch_enabled", server_default=None)


def downgrade() -> None:
    op.drop_column("wechat_sources", "auto_fetch_last_scheduled_at")
    op.drop_column("wechat_sources", "auto_fetch_enabled")
