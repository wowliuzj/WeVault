"""create wechat auth tables

Revision ID: 20260610_0002
Revises: 20260610_0001
Create Date: 2026-06-10
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260610_0002"
down_revision: str | None = "20260610_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

token_status = postgresql.ENUM(
    "valid",
    "expired",
    "invalid",
    "unknown",
    name="token_status",
    create_type=False,
)
wechat_session_status = postgresql.ENUM(
    "valid",
    "expired",
    "invalid",
    "unknown",
    name="wechat_session_status",
    create_type=False,
)
wechat_login_status = postgresql.ENUM(
    "waiting_scan",
    "scanned",
    "confirmed",
    "expired",
    "failed",
    name="wechat_login_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    token_status.create(bind, checkfirst=True)
    wechat_session_status.create(bind, checkfirst=True)
    wechat_login_status.create(bind, checkfirst=True)

    op.create_table(
        "wechat_accounts",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("nickname", sa.String(length=120), nullable=False),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("username", sa.String(length=120), nullable=True),
        sa.Column("biz", sa.String(length=120), nullable=True),
        sa.Column("token_status", token_status, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_wechat_accounts_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_wechat_accounts")),
        sa.UniqueConstraint("user_id", "biz", name="uq_wechat_accounts_user_biz"),
    )
    op.create_index(op.f("ix_wechat_accounts_user_id"), "wechat_accounts", ["user_id"])

    op.create_table(
        "wechat_sessions",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("wechat_account_id", sa.UUID(), nullable=False),
        sa.Column("token_encrypted", sa.Text(), nullable=True),
        sa.Column("cookies_encrypted", sa.Text(), nullable=True),
        sa.Column("raw_session_encrypted", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", wechat_session_status, nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_wechat_sessions_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["wechat_account_id"],
            ["wechat_accounts.id"],
            name=op.f("fk_wechat_sessions_wechat_account_id_wechat_accounts"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_wechat_sessions")),
    )
    op.create_index(op.f("ix_wechat_sessions_user_id"), "wechat_sessions", ["user_id"])
    op.create_index(
        op.f("ix_wechat_sessions_wechat_account_id"),
        "wechat_sessions",
        ["wechat_account_id"],
    )

    op.create_table(
        "wechat_login_sessions",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("login_id", sa.String(length=80), nullable=False),
        sa.Column("status", wechat_login_status, nullable=False),
        sa.Column("qr_url", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("raw_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_wechat_login_sessions_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_wechat_login_sessions")),
    )
    op.create_index(
        op.f("ix_wechat_login_sessions_login_id"),
        "wechat_login_sessions",
        ["login_id"],
        unique=True,
    )
    op.create_index(op.f("ix_wechat_login_sessions_status"), "wechat_login_sessions", ["status"])
    op.create_index(op.f("ix_wechat_login_sessions_user_id"), "wechat_login_sessions", ["user_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_wechat_login_sessions_user_id"), table_name="wechat_login_sessions")
    op.drop_index(op.f("ix_wechat_login_sessions_status"), table_name="wechat_login_sessions")
    op.drop_index(op.f("ix_wechat_login_sessions_login_id"), table_name="wechat_login_sessions")
    op.drop_table("wechat_login_sessions")
    op.drop_index(op.f("ix_wechat_sessions_wechat_account_id"), table_name="wechat_sessions")
    op.drop_index(op.f("ix_wechat_sessions_user_id"), table_name="wechat_sessions")
    op.drop_table("wechat_sessions")
    op.drop_index(op.f("ix_wechat_accounts_user_id"), table_name="wechat_accounts")
    op.drop_table("wechat_accounts")

    wechat_login_status.drop(op.get_bind(), checkfirst=True)
    wechat_session_status.drop(op.get_bind(), checkfirst=True)
    token_status.drop(op.get_bind(), checkfirst=True)
