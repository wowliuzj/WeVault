from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.enums import TaskStatus, TaskType
from app.models.task import CollectionTask
from app.models.user import User
from app.models.wechat import WechatSource

router = APIRouter()


class TaskResponse(BaseModel):
    id: str
    task_type: str
    status: str
    progress_current: int
    progress_total: int
    target_type: str | None = None
    target_id: str | None = None
    payload: dict[str, Any] | None = None
    note: str
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class CreateSourceArticleTaskRequest(BaseModel):
    source_id: UUID
    range: Literal["7d", "30d", "90d", "all"] = "7d"
    limit: Literal[0, 30, 50, 100] = 50
    fetch_content: bool = False
    fetch_comments: bool = False
    skip_existing: bool = True


def task_note(task: CollectionTask, source_name: str | None = None) -> str:
    payload = task.payload or {}
    range_label = {
        "7d": "最近 7 天",
        "30d": "最近 30 天",
        "90d": "最近 90 天",
        "all": "全部",
    }.get(payload.get("range"), "最近 7 天")
    limit = payload.get("limit", 50)
    limit_label = "不设限" if limit == 0 else f"最多 {limit} 篇"
    content_label = "含正文" if payload.get("fetch_content") else "仅列表"
    comment_label = "含评论" if payload.get("fetch_comments") else "不含评论"
    source_label = source_name or "公众号源"
    return f"{source_label} · {range_label} · {limit_label} · {content_label} · {comment_label}"


def serialize_task(task: CollectionTask, source_name: str | None = None) -> TaskResponse:
    return TaskResponse(
        id=str(task.id),
        task_type=task.task_type.value,
        status=task.status.value,
        progress_current=task.progress_current,
        progress_total=task.progress_total,
        target_type=task.target_type,
        target_id=str(task.target_id) if task.target_id else None,
        payload=task.payload,
        note=task_note(task, source_name),
        error_message=task.error_message,
        created_at=task.created_at,
        started_at=task.started_at,
        finished_at=task.finished_at,
    )


async def get_user_source(db: AsyncSession, user: User, source_id: UUID) -> WechatSource:
    result = await db.execute(
        select(WechatSource).where(
            WechatSource.id == source_id,
            WechatSource.user_id == user.id,
        )
    )
    source = result.scalar_one_or_none()
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="公众号源不存在。",
        )
    return source


@router.get("", response_model=list[TaskResponse])
async def list_tasks(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TaskResponse]:
    rows = await db.execute(
        select(CollectionTask, WechatSource.name)
        .outerjoin(
            WechatSource,
            (CollectionTask.target_id == WechatSource.id)
            & (CollectionTask.target_type == "wechat_source"),
        )
        .where(CollectionTask.user_id == current_user.id)
        .order_by(CollectionTask.created_at.desc())
        .limit(100)
    )
    return [serialize_task(task, source_name) for task, source_name in rows.all()]


@router.post("/source-articles", response_model=TaskResponse)
async def create_source_article_task(
    payload: CreateSourceArticleTaskRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TaskResponse:
    source = await get_user_source(db, current_user, payload.source_id)
    task_payload = {
        "source_id": str(source.id),
        "range": payload.range,
        "limit": payload.limit,
        "fetch_content": payload.fetch_content,
        "fetch_comments": payload.fetch_comments,
        "skip_existing": payload.skip_existing,
        "run_mode": "immediate",
    }
    task = CollectionTask(
        user_id=current_user.id,
        task_type=TaskType.FETCH_SOURCE_ARTICLES,
        status=TaskStatus.PENDING,
        progress_current=0,
        progress_total=0,
        retry_count=0,
        target_type="wechat_source",
        target_id=source.id,
        payload=task_payload,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return serialize_task(task, source.name)
