"""expand article title length

Revision ID: 20260615_0011
Revises: 20260612_0010
Create Date: 2026-06-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260615_0011"
down_revision: str | None = "20260612_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index(op.f("ix_articles_title"), table_name="articles")
    op.alter_column(
        "articles",
        "title",
        existing_type=sa.String(length=300),
        type_=sa.Text(),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.execute("UPDATE articles SET title = left(title, 300) WHERE char_length(title) > 300")
    op.alter_column(
        "articles",
        "title",
        existing_type=sa.Text(),
        type_=sa.String(length=300),
        existing_nullable=False,
    )
    op.create_index(op.f("ix_articles_title"), "articles", ["title"], unique=False)
