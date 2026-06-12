"""remove comment collection tables

Revision ID: 20260612_0010
Revises: 20260612_0009
Create Date: 2026-06-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260612_0010"
down_revision: str | None = "20260612_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DELETE FROM collection_tasks WHERE task_type = 'fetch_article_comments'")
    op.drop_index(op.f("ix_article_comments_wechat_comment_id"), table_name="article_comments")
    op.drop_index(op.f("ix_article_comments_user_id"), table_name="article_comments")
    op.drop_index(op.f("ix_article_comments_publish_time"), table_name="article_comments")
    op.drop_index(op.f("ix_article_comments_article_id"), table_name="article_comments")
    op.drop_table("article_comments")
    op.drop_column("articles", "comment_status")
    op.drop_column("wechat_sources", "comment_fetch_policy")
    op.drop_column("wechat_sources", "auto_fetch_comments")


def downgrade() -> None:
    article_comment_status = sa.Enum(
        "pending",
        "running",
        "fetched",
        "failed",
        name="article_comment_status",
    )
    article_comment_status.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "wechat_sources",
        sa.Column("auto_fetch_comments", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "wechat_sources",
        sa.Column(
            "comment_fetch_policy",
            sa.String(length=40),
            nullable=False,
            server_default="none",
        ),
    )
    op.add_column(
        "articles",
        sa.Column(
            "comment_status",
            article_comment_status,
            nullable=False,
            server_default="pending",
        ),
    )
    op.create_table(
        "article_comments",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("article_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("wechat_comment_id", sa.String(length=160), nullable=False),
        sa.Column("nickname", sa.String(length=120), nullable=True),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("like_count", sa.Integer(), nullable=False),
        sa.Column("reply_count", sa.Integer(), nullable=False),
        sa.Column("publish_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["articles.id"],
            name=op.f("fk_article_comments_article_id_articles"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_article_comments_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_article_comments")),
        sa.UniqueConstraint(
            "article_id",
            "wechat_comment_id",
            name="uq_article_comments_article_wechat_id",
        ),
    )
    op.create_index(op.f("ix_article_comments_article_id"), "article_comments", ["article_id"])
    op.create_index(op.f("ix_article_comments_publish_time"), "article_comments", ["publish_time"])
    op.create_index(op.f("ix_article_comments_user_id"), "article_comments", ["user_id"])
    op.create_index(
        op.f("ix_article_comments_wechat_comment_id"),
        "article_comments",
        ["wechat_comment_id"],
    )
