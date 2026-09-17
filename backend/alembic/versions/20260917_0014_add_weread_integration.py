"""add WeRead authorization and supplemental identifiers

Revision ID: 20260917_0014
Revises: 20260622_0013
Create Date: 2026-09-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260917_0014"
down_revision: str | None = "20260622_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "weread_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("credentials_encrypted", sa.Text(), nullable=True),
        sa.Column("nickname", sa.String(length=120), nullable=True),
        sa.Column(
            "status",
            sa.Enum("valid", "expired", "invalid", "unknown", name="weread_session_status"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_weread_sessions_user"),
    )
    op.create_index(op.f("ix_weread_sessions_user_id"), "weread_sessions", ["user_id"])

    op.create_table(
        "weread_login_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("login_id", sa.String(length=80), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "waiting_scan",
                "scanned",
                "confirmed",
                "expired",
                "failed",
                name="weread_login_status",
            ),
            nullable=False,
        ),
        sa.Column("qr_url", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("raw_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("login_id"),
    )
    op.create_index(
        op.f("ix_weread_login_sessions_login_id"), "weread_login_sessions", ["login_id"]
    )
    op.create_index(op.f("ix_weread_login_sessions_status"), "weread_login_sessions", ["status"])
    op.create_index(op.f("ix_weread_login_sessions_user_id"), "weread_login_sessions", ["user_id"])

    op.add_column(
        "wechat_sources", sa.Column("weread_book_id", sa.String(length=160), nullable=True)
    )
    op.add_column(
        "wechat_sources", sa.Column("weread_matched_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index(op.f("ix_wechat_sources_weread_book_id"), "wechat_sources", ["weread_book_id"])
    op.create_unique_constraint(
        "uq_wechat_sources_user_weread_book", "wechat_sources", ["user_id", "weread_book_id"]
    )

    op.add_column("articles", sa.Column("weread_review_id", sa.String(length=255), nullable=True))
    op.add_column("articles", sa.Column("weread_original_id", sa.String(length=255), nullable=True))
    op.create_index(op.f("ix_articles_weread_review_id"), "articles", ["weread_review_id"])
    op.create_unique_constraint(
        "uq_articles_user_weread_review", "articles", ["user_id", "weread_review_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_articles_user_weread_review", "articles", type_="unique")
    op.drop_index(op.f("ix_articles_weread_review_id"), table_name="articles")
    op.drop_column("articles", "weread_original_id")
    op.drop_column("articles", "weread_review_id")
    op.drop_constraint("uq_wechat_sources_user_weread_book", "wechat_sources", type_="unique")
    op.drop_index(op.f("ix_wechat_sources_weread_book_id"), table_name="wechat_sources")
    op.drop_column("wechat_sources", "weread_matched_at")
    op.drop_column("wechat_sources", "weread_book_id")
    op.drop_index(op.f("ix_weread_login_sessions_user_id"), table_name="weread_login_sessions")
    op.drop_index(op.f("ix_weread_login_sessions_status"), table_name="weread_login_sessions")
    op.drop_index(op.f("ix_weread_login_sessions_login_id"), table_name="weread_login_sessions")
    op.drop_table("weread_login_sessions")
    op.drop_index(op.f("ix_weread_sessions_user_id"), table_name="weread_sessions")
    op.drop_table("weread_sessions")
    op.execute("DROP TYPE IF EXISTS weread_login_status")
    op.execute("DROP TYPE IF EXISTS weread_session_status")
