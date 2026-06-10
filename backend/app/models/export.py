from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import ExportFormat, TaskStatus


class ExportJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "export_jobs"

    user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(180))
    format: Mapped[ExportFormat] = mapped_column(Enum(ExportFormat, name="export_format"))
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, name="export_status"),
        default=TaskStatus.PENDING,
        index=True,
    )
    article_ids: Mapped[list[str]] = mapped_column(JSONB)
    options: Mapped[dict | None] = mapped_column(JSONB)
    error_message: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    files = relationship("ExportFile", back_populates="export_job")


class ExportFile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "export_files"

    export_job_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("export_jobs.id"),
        index=True,
    )
    file_name: Mapped[str] = mapped_column(String(240))
    file_path: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(default=0)

    export_job = relationship("ExportJob", back_populates="files")
