"""create content tables

Revision ID: 20260610_0003
Revises: 20260610_0002
Create Date: 2026-06-10
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260610_0003"
down_revision: str | None = "20260610_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

source_from = postgresql.ENUM(
    "search",
    "article_url",
    "manual",
    name="source_from",
    create_type=False,
)
source_status = postgresql.ENUM(
    "active",
    "paused",
    "failed",
    name="source_status",
    create_type=False,
)
article_content_status = postgresql.ENUM(
    "pending",
    "running",
    "fetched",
    "failed",
    name="article_content_status",
    create_type=False,
)
article_comment_status = postgresql.ENUM(
    "pending",
    "running",
    "fetched",
    "failed",
    name="article_comment_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    source_from.create(bind, checkfirst=True)
    source_status.create(bind, checkfirst=True)
    article_content_status.create(bind, checkfirst=True)
    article_comment_status.create(bind, checkfirst=True)

    op.create_table(
        "wechat_sources",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("wechat_account_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("alias", sa.String(length=120), nullable=True),
        sa.Column("fakeid", sa.String(length=160), nullable=True),
        sa.Column("biz", sa.String(length=160), nullable=True),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_from", source_from, nullable=False),
        sa.Column("status", source_status, nullable=False),
        sa.Column("auto_fetch_content", sa.Boolean(), nullable=False),
        sa.Column("auto_fetch_comments", sa.Boolean(), nullable=False),
        sa.Column("fetch_limit_per_run", sa.Integer(), nullable=False),
        sa.Column("fetch_since_days", sa.Integer(), nullable=True),
        sa.Column("comment_fetch_policy", sa.String(length=40), nullable=False),
        sa.Column("last_list_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_content_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_wechat_sources_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["wechat_account_id"],
            ["wechat_accounts.id"],
            name=op.f("fk_wechat_sources_wechat_account_id_wechat_accounts"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_wechat_sources")),
        sa.UniqueConstraint("user_id", "fakeid", name="uq_wechat_sources_user_fakeid"),
    )
    op.create_index(op.f("ix_wechat_sources_biz"), "wechat_sources", ["biz"])
    op.create_index(op.f("ix_wechat_sources_fakeid"), "wechat_sources", ["fakeid"])
    op.create_index(op.f("ix_wechat_sources_name"), "wechat_sources", ["name"])
    op.create_index(op.f("ix_wechat_sources_user_id"), "wechat_sources", ["user_id"])
    op.create_index(
        op.f("ix_wechat_sources_wechat_account_id"),
        "wechat_sources",
        ["wechat_account_id"],
    )

    op.create_table(
        "articles",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("wechat_account_id", sa.UUID(), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("author", sa.String(length=120), nullable=True),
        sa.Column("digest", sa.Text(), nullable=True),
        sa.Column("cover_url", sa.Text(), nullable=True),
        sa.Column("original_url", sa.Text(), nullable=False),
        sa.Column("publish_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("msgid", sa.String(length=120), nullable=True),
        sa.Column("idx", sa.Integer(), nullable=True),
        sa.Column("biz", sa.String(length=160), nullable=True),
        sa.Column("appmsgid", sa.String(length=120), nullable=True),
        sa.Column("itemidx", sa.Integer(), nullable=True),
        sa.Column("content_status", article_content_status, nullable=False),
        sa.Column("comment_status", article_comment_status, nullable=False),
        sa.Column("raw_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["wechat_sources.id"],
            name=op.f("fk_articles_source_id_wechat_sources"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_articles_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["wechat_account_id"],
            ["wechat_accounts.id"],
            name=op.f("fk_articles_wechat_account_id_wechat_accounts"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_articles")),
        sa.UniqueConstraint(
            "source_id",
            "appmsgid",
            "itemidx",
            name="uq_articles_source_appmsg_item",
        ),
    )
    op.create_index(op.f("ix_articles_appmsgid"), "articles", ["appmsgid"])
    op.create_index(op.f("ix_articles_biz"), "articles", ["biz"])
    op.create_index(op.f("ix_articles_msgid"), "articles", ["msgid"])
    op.create_index(op.f("ix_articles_publish_time"), "articles", ["publish_time"])
    op.create_index(op.f("ix_articles_source_id"), "articles", ["source_id"])
    op.create_index(op.f("ix_articles_title"), "articles", ["title"])
    op.create_index(op.f("ix_articles_user_id"), "articles", ["user_id"])
    op.create_index(
        op.f("ix_articles_user_source_publish_time"),
        "articles",
        ["user_id", "source_id", "publish_time"],
    )
    op.create_index(
        op.f("ix_articles_wechat_account_id"),
        "articles",
        ["wechat_account_id"],
    )

    op.create_table(
        "article_contents",
        sa.Column("article_id", sa.UUID(), nullable=False),
        sa.Column("raw_html", sa.Text(), nullable=True),
        sa.Column("clean_html", sa.Text(), nullable=True),
        sa.Column("markdown", sa.Text(), nullable=True),
        sa.Column("plain_text", sa.Text(), nullable=True),
        sa.Column("assets_manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["articles.id"],
            name=op.f("fk_article_contents_article_id_articles"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_article_contents")),
    )
    op.create_index(
        op.f("ix_article_contents_article_id"),
        "article_contents",
        ["article_id"],
        unique=True,
    )

    op.create_table(
        "article_comments",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("article_id", sa.UUID(), nullable=False),
        sa.Column("wechat_comment_id", sa.String(length=160), nullable=False),
        sa.Column("nickname", sa.String(length=120), nullable=True),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("like_count", sa.Integer(), nullable=False),
        sa.Column("reply_count", sa.Integer(), nullable=False),
        sa.Column("publish_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
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


def downgrade() -> None:
    op.drop_index(op.f("ix_article_comments_wechat_comment_id"), table_name="article_comments")
    op.drop_index(op.f("ix_article_comments_user_id"), table_name="article_comments")
    op.drop_index(op.f("ix_article_comments_publish_time"), table_name="article_comments")
    op.drop_index(op.f("ix_article_comments_article_id"), table_name="article_comments")
    op.drop_table("article_comments")
    op.drop_index(op.f("ix_article_contents_article_id"), table_name="article_contents")
    op.drop_table("article_contents")
    op.drop_index(op.f("ix_articles_wechat_account_id"), table_name="articles")
    op.drop_index(op.f("ix_articles_user_source_publish_time"), table_name="articles")
    op.drop_index(op.f("ix_articles_user_id"), table_name="articles")
    op.drop_index(op.f("ix_articles_title"), table_name="articles")
    op.drop_index(op.f("ix_articles_source_id"), table_name="articles")
    op.drop_index(op.f("ix_articles_publish_time"), table_name="articles")
    op.drop_index(op.f("ix_articles_msgid"), table_name="articles")
    op.drop_index(op.f("ix_articles_biz"), table_name="articles")
    op.drop_index(op.f("ix_articles_appmsgid"), table_name="articles")
    op.drop_table("articles")
    op.drop_index(op.f("ix_wechat_sources_wechat_account_id"), table_name="wechat_sources")
    op.drop_index(op.f("ix_wechat_sources_user_id"), table_name="wechat_sources")
    op.drop_index(op.f("ix_wechat_sources_name"), table_name="wechat_sources")
    op.drop_index(op.f("ix_wechat_sources_fakeid"), table_name="wechat_sources")
    op.drop_index(op.f("ix_wechat_sources_biz"), table_name="wechat_sources")
    op.drop_table("wechat_sources")

    article_comment_status.drop(op.get_bind(), checkfirst=True)
    article_content_status.drop(op.get_bind(), checkfirst=True)
    source_status.drop(op.get_bind(), checkfirst=True)
    source_from.drop(op.get_bind(), checkfirst=True)
