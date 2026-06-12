from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import FetchStatus


def enum_values(enum_cls: type) -> list[str]:
    return [item.value for item in enum_cls]


class Article(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "articles"
    __table_args__ = (
        UniqueConstraint("source_id", "appmsgid", "itemidx", name="uq_articles_source_appmsg_item"),
        Index("ix_articles_user_source_publish_time", "user_id", "source_id", "publish_time"),
    )

    user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("users.id"), index=True)
    source_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("wechat_sources.id"),
        index=True,
    )
    wechat_account_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("wechat_accounts.id"),
        index=True,
    )
    title: Mapped[str] = mapped_column(String(300), index=True)
    author: Mapped[str | None] = mapped_column(String(120))
    digest: Mapped[str | None] = mapped_column(Text)
    cover_url: Mapped[str | None] = mapped_column(Text)
    cover_storage_path: Mapped[str | None] = mapped_column(Text)
    cover_content_type: Mapped[str | None] = mapped_column(String(120))
    original_url: Mapped[str] = mapped_column(Text)
    publish_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    msgid: Mapped[str | None] = mapped_column(String(120), index=True)
    idx: Mapped[int | None] = mapped_column()
    biz: Mapped[str | None] = mapped_column(String(160), index=True)
    appmsgid: Mapped[str | None] = mapped_column(String(120), index=True)
    itemidx: Mapped[int | None] = mapped_column()
    content_status: Mapped[FetchStatus] = mapped_column(
        Enum(FetchStatus, name="article_content_status", values_callable=enum_values),
        default=FetchStatus.PENDING,
    )
    comment_status: Mapped[FetchStatus] = mapped_column(
        Enum(FetchStatus, name="article_comment_status", values_callable=enum_values),
        default=FetchStatus.PENDING,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    raw_data: Mapped[dict | None] = mapped_column(JSONB)

    user = relationship("User", back_populates="articles")
    source = relationship("WechatSource", back_populates="articles")
    content = relationship("ArticleContent", back_populates="article", uselist=False)
    comments = relationship("ArticleComment", back_populates="article")


class ArticleContent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "article_contents"

    article_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("articles.id"),
        unique=True,
        index=True,
    )
    raw_html: Mapped[str | None] = mapped_column(Text)
    clean_html: Mapped[str | None] = mapped_column(Text)
    markdown: Mapped[str | None] = mapped_column(Text)
    plain_text: Mapped[str | None] = mapped_column(Text)
    assets_manifest: Mapped[dict | None] = mapped_column(JSONB)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    article = relationship("Article", back_populates="content")


class ArticleComment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "article_comments"
    __table_args__ = (
        UniqueConstraint(
            "article_id",
            "wechat_comment_id",
            name="uq_article_comments_article_wechat_id",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("users.id"), index=True)
    article_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("articles.id"),
        index=True,
    )
    wechat_comment_id: Mapped[str] = mapped_column(String(160), index=True)
    nickname: Mapped[str | None] = mapped_column(String(120))
    avatar_url: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    like_count: Mapped[int] = mapped_column(default=0)
    reply_count: Mapped[int] = mapped_column(default=0)
    publish_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    raw_data: Mapped[dict | None] = mapped_column(JSONB)

    article = relationship("Article", back_populates="comments")
