from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import SourceFrom, SourceStatus, TokenStatus


class WechatAccount(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "wechat_accounts"
    __table_args__ = (UniqueConstraint("user_id", "biz", name="uq_wechat_accounts_user_biz"),)

    user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("users.id"), index=True)
    nickname: Mapped[str] = mapped_column(String(120))
    avatar_url: Mapped[str | None] = mapped_column(Text)
    username: Mapped[str | None] = mapped_column(String(120))
    biz: Mapped[str | None] = mapped_column(String(120))
    token_status: Mapped[TokenStatus] = mapped_column(
        Enum(TokenStatus, name="token_status"),
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
        Enum(TokenStatus, name="wechat_session_status"),
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
    description: Mapped[str | None] = mapped_column(Text)
    source_from: Mapped[SourceFrom] = mapped_column(
        Enum(SourceFrom, name="source_from"),
        default=SourceFrom.SEARCH,
    )
    status: Mapped[SourceStatus] = mapped_column(
        Enum(SourceStatus, name="source_status"),
        default=SourceStatus.ACTIVE,
    )
    auto_fetch_content: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_fetch_comments: Mapped[bool] = mapped_column(Boolean, default=False)
    fetch_limit_per_run: Mapped[int] = mapped_column(default=50)
    fetch_since_days: Mapped[int | None] = mapped_column()
    comment_fetch_policy: Mapped[str] = mapped_column(String(40), default="none")
    last_list_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_content_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_data: Mapped[dict | None] = mapped_column(JSONB)

    user = relationship("User", back_populates="sources")
    wechat_account = relationship("WechatAccount", back_populates="sources")
    articles = relationship("Article", back_populates="source")

