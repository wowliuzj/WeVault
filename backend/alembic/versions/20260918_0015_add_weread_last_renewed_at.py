"""add WeRead renewal timestamp

Revision ID: 20260918_0015
Revises: 20260917_0014
Create Date: 2026-09-18
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260918_0015"
down_revision: str | None = "20260917_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "weread_sessions",
        sa.Column("last_renewed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("weread_sessions", "last_renewed_at")
