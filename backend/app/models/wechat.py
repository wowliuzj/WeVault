from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import SourceFrom, SourceStatus, TokenStatus, WechatLoginStatus


def enum_values(enum_cls: type) -> list[str]:
    return [item.value for item in enum_cls]


class WechatAccount(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "wechat_accounts"
    __table_args__ = (UniqueConstraint("user_id", "biz", name="uq_wechat_accounts_user_biz"),)

    user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("users.id"), index=True)
    nickname: Mapped[str] = mapped_column(String(120))
    avatar_url: Mapped[str | None] = mapped_column(Text)
    username: Mapped[str | None] = mapped_column(String(120))
    biz: Mapped[str | None] = mapped_column(String(120))
    token_status: Mapped[TokenStatus] = mapped_column(
        Enum(TokenStatus, name="token_status", values_callable=enum_values),
        default=TokenStatus.UNKNOWN,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user = relationship("User", back_populates="wechat_accounts")
    sessions = relationship("WechatSession", back_populates="wechat_account")
    sources = relationship("WechatSource", back_populates="wechat_account")


class WechatSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "wechat_sessions"

    user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("users.id"), index=True)
    wechat_account_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("wechat_accounts.id"),
        index=True,
    )
    token_encrypted: Mapped[str | None] = mapped_column(Text)
    cookies_encrypted: Mapped[str | None] = mapped_column(Text)
    raw_session_encrypted: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[TokenStatus] = mapped_column(
        Enum(TokenStatus, name="wechat_session_status", values_callable=enum_values),
        default=TokenStatus.UNKNOWN,
    )

    wechat_account = relationship("WechatAccount", back_populates="sessions")


class WechatSource(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "wechat_sources"
    __table_args__ = (UniqueConstraint("user_id", "fakeid", name="uq_wechat_sources_user_fakeid"),)

    user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("users.id"), index=True)
    wechat_account_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("wechat_accounts.id"),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120), index=True)
    alias: Mapped[str | None] = mapped_column(String(120))
    fakeid: Mapped[str | None] = mapped_column(String(160), index=True)
    biz: Mapped[str | None] = mapped_column(String(160), index=True)
    avatar_url: Mapped[str | None] = mapped_column(Text)
    avatar_storage_path: Mapped[str | None] = mapped_column(Text)
    avatar_content_type: Mapped[str | None] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    source_from: Mapped[SourceFrom] = mapped_column(
        Enum(SourceFrom, name="source_from", values_callable=enum_values),
        default=SourceFrom.SEARCH,
    )
    status: Mapped[SourceStatus] = mapped_column(
        Enum(SourceStatus, name="source_status", values_callable=enum_values),
        default=SourceStatus.ACTIVE,
    )
    auto_fetch_content: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_fetch_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_fetch_last_scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    fetch_limit_per_run: Mapped[int] = mapped_column(default=50)
    fetch_since_days: Mapped[int | None] = mapped_column()
    last_list_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_content_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    raw_data: Mapped[dict | None] = mapped_column(JSONB)

    user = relationship("User", back_populates="sources")
    wechat_account = relationship("WechatAccount", back_populates="sources")
    articles = relationship("Article", back_populates="source")


class WechatLoginSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "wechat_login_sessions"

    user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("users.id"), index=True)
    login_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    status: Mapped[WechatLoginStatus] = mapped_column(
        Enum(
            WechatLoginStatus,
            name="wechat_login_status",
            values_callable=enum_values,
        ),
        default=WechatLoginStatus.WAITING_SCAN,
        index=True,
    )
    qr_url: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    raw_data: Mapped[dict | None] = mapped_column(JSONB)
