from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import FileResponse

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.models.enums import ExportFormat, TaskStatus, TaskType
from app.models.export import ExportFile, ExportJob
from app.models.task import CollectionTask
from app.models.user import User

router = APIRouter()


class ExportFileResponse(BaseModel):
    id: str
    file_name: str
    file_path: str
    content_type: str
    size_bytes: int


class ExportJobResponse(BaseModel):
    id: str
    name: str
    format: str
    status: str
    note: str
    created_at: datetime
    finished_at: datetime | None = None
    expires_at: datetime | None = None
    error_message: str | None = None
    files: list[ExportFileResponse] = []


class CreateExportRequest(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    format: Literal["pdf", "docx", "markdown", "zip"]
    formats: list[Literal["pdf", "docx", "markdown"]] | None = None
    article_ids: list[UUID] = Field(min_length=1)


def export_note(job: ExportJob) -> str:
    if job.format == ExportFormat.ZIP and isinstance(job.options, dict):
        raw_formats = job.options.get("formats")
        if isinstance(raw_formats, list) and raw_formats:
            labels = {"pdf": "PDF", "docx": "DOCX", "markdown": "Markdown"}
            selected = [labels[value] for value in raw_formats if value in labels]
            format_label = "ZIP · " + " / ".join(selected) if selected else "ZIP"
        else:
            format_label = "ZIP"
    else:
        format_label = {
            ExportFormat.PDF: "PDF",
            ExportFormat.DOCX: "DOCX",
            ExportFormat.MARKDOWN: "Markdown",
            ExportFormat.ZIP: "ZIP",
        }[job.format]
    count = len(job.article_ids)
    if job.status == TaskStatus.SUCCEEDED:
        return f"{format_label} · {count} 篇文章"
    if job.status == TaskStatus.FAILED:
        return job.error_message or f"{format_label} · 导出失败"
    if job.status == TaskStatus.RUNNING:
        return f"{format_label} · 导出中"
    return f"{format_label} · 已排队"


def serialize_export_file(file: ExportFile) -> ExportFileResponse:
    return ExportFileResponse(
        id=str(file.id),
        file_name=file.file_name,
        file_path=file.file_path,
        content_type=file.content_type,
        size_bytes=file.size_bytes,
    )


def serialize_export_job(
    job: ExportJob,
    *,
    files: list[ExportFile] | None = None,
) -> ExportJobResponse:
    expires_at = None
    if job.finished_at and job.status == TaskStatus.SUCCEEDED:
        expires_at = job.finished_at + timedelta(days=settings.export_file_ttl_days)

    return ExportJobResponse(
        id=str(job.id),
        name=job.name,
        format=job.format.value,
        status=job.status.value,
        note=export_note(job),
        created_at=job.created_at,
        finished_at=job.finished_at,
        expires_at=expires_at,
        error_message=job.error_message,
        files=[serialize_export_file(file) for file in files or []],
    )


async def get_user_export_job(db: AsyncSession, user: User, job_id: UUID) -> ExportJob:
    result = await db.execute(
        select(ExportJob)
        .where(ExportJob.id == job_id, ExportJob.user_id == user.id)
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="导出任务不存在。")
    return job


@router.get("", response_model=list[ExportJobResponse])
async def list_export_jobs(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ExportJobResponse]:
    result = await db.execute(
        select(ExportJob)
        .where(ExportJob.user_id == current_user.id)
        .order_by(ExportJob.created_at.desc())
    )
    jobs = list(result.scalars().all())
    if not jobs:
        return []

    job_ids = [job.id for job in jobs]
    file_result = await db.execute(
        select(ExportFile).where(ExportFile.export_job_id.in_(job_ids))
    )
    files_by_job: dict[UUID, list[ExportFile]] = {job.id: [] for job in jobs}
    for file in file_result.scalars().all():
        files_by_job[file.export_job_id].append(file)

    return [
        serialize_export_job(job, files=files_by_job.get(job.id, []))
        for job in jobs
    ]


@router.post("")
async def create_export_job(
    payload: CreateExportRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    format_value = ExportFormat(payload.format)
    options: dict[str, object] = {"run_mode": "immediate"}
    if format_value == ExportFormat.ZIP:
        formats = list(dict.fromkeys(payload.formats or []))
        if not formats:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ZIP 导出需要选择至少一个格式。",
            )
        options["formats"] = formats

    job = ExportJob(
        user_id=current_user.id,
        name=payload.name,
        format=format_value,
        status=TaskStatus.PENDING,
        article_ids=[str(article_id) for article_id in payload.article_ids],
        options=options,
    )
    db.add(job)
    await db.flush()
    task = CollectionTask(
        user_id=current_user.id,
        task_type=TaskType.EXPORT_ARTICLES,
        status=TaskStatus.PENDING,
        progress_current=0,
        progress_total=len(payload.article_ids),
        retry_count=0,
        target_type="export_job",
        target_id=job.id,
        payload={
            "export_job_id": str(job.id),
            "export_job_name": payload.name,
            "format": payload.format,
            "formats": options.get("formats"),
            "article_ids": [str(article_id) for article_id in payload.article_ids],
            "run_mode": "immediate",
        },
    )
    db.add(task)
    await db.commit()
    await db.refresh(job)
    await db.refresh(task)
    return {"status": "queued", "task_id": str(task.id), "job_id": str(job.id)}


@router.get("/{job_id}/download")
async def download_export_file(
    job_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    job = await get_user_export_job(db, current_user, job_id)
    file_result = await db.execute(
        select(ExportFile).where(ExportFile.export_job_id == job.id).limit(1)
    )
    file = file_result.scalar_one_or_none()
    if job.status != TaskStatus.SUCCEEDED or file is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="导出文件不存在。")
    path = Path(file.file_path)
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="导出文件已丢失。")
    return FileResponse(path, filename=file.file_name, media_type=file.content_type)
