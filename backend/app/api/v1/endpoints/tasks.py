from datetime import UTC, date, datetime
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
    range: Literal["7d", "30d", "90d", "custom", "all"] = "7d"
    start_date: date | None = None
    end_date: date | None = None
    limit: Literal[0, 30, 50, 100] = 50
    fetch_content: bool = False
    skip_existing: bool = True


def task_run_mode(task: CollectionTask) -> str:
    payload = task.payload or {}
    run_mode = payload.get("run_mode")
    return run_mode if isinstance(run_mode, str) else "immediate"


def task_note(task: CollectionTask, source_name: str | None = None) -> str:
    payload = task.payload or {}
    article_ids = payload.get("article_ids")
    if isinstance(article_ids, list):
        action_label = {
            TaskType.FETCH_ARTICLE_CONTENT: "抓取正文",
        }.get(task.task_type, "处理文章")
        return f"文章 {len(article_ids)} 篇 · {action_label}"

    range_label = {
        "7d": "最近 7 天",
        "30d": "最近 30 天",
        "90d": "最近 90 天",
        "all": "全部",
        "custom": "自定义",
    }.get(payload.get("range"), "最近 7 天")
    if payload.get("range") == "custom":
        start_date = payload.get("start_date") or "未设置"
        end_date = payload.get("end_date") or "未设置"
        range_label = f"{start_date} 至 {end_date}"
    limit = payload.get("limit", 50)
    limit_label = "不设限" if limit == 0 else f"最多 {limit} 篇"
    content_label = "含正文" if payload.get("fetch_content") else "仅列表"
    source_label = source_name or "公众号源"
    return f"{source_label} · {range_label} · {limit_label} · {content_label}"


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


async def get_user_task(db: AsyncSession, user: User, task_id: UUID) -> CollectionTask:
    result = await db.execute(
        select(CollectionTask).where(
            CollectionTask.id == task_id,
            CollectionTask.user_id == user.id,
        )
    )
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="采集任务不存在。",
        )
    return task


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
    if payload.range == "custom":
        if payload.start_date is None or payload.end_date is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="自定义时间范围需要开始日期和结束日期。",
            )
        if payload.start_date > payload.end_date:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="开始日期不能晚于结束日期。",
            )

    source = await get_user_source(db, current_user, payload.source_id)
    task_payload = {
        "source_id": str(source.id),
        "range": payload.range,
        "limit": payload.limit,
        "fetch_content": payload.fetch_content,
        "skip_existing": payload.skip_existing,
        "run_mode": "immediate",
    }
    if payload.range == "custom":
        task_payload["start_date"] = payload.start_date.isoformat() if payload.start_date else None
        task_payload["end_date"] = payload.end_date.isoformat() if payload.end_date else None
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


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TaskResponse:
    task = await get_user_task(db, current_user, task_id)
    source_name = None
    if task.target_type == "wechat_source" and task.target_id:
        result = await db.execute(
            select(WechatSource.name).where(
                WechatSource.id == task.target_id,
                WechatSource.user_id == current_user.id,
            )
        )
        source_name = result.scalar_one_or_none()
    return serialize_task(task, source_name)


@router.post("/{task_id}/start", response_model=TaskResponse)
async def start_task(
    task_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TaskResponse:
    task = await get_user_task(db, current_user, task_id)
    run_mode = task_run_mode(task)
    if run_mode == "immediate":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="立即执行任务不支持手动开始。",
        )
    if task.status == TaskStatus.RUNNING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="任务已经在运行中。",
        )
    if run_mode == "scheduled" and task.status == TaskStatus.CANCELLED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="指定时间任务停止后不能再次开始。",
        )

    task.status = TaskStatus.PENDING
    task.finished_at = None
    task.error_message = None
    await db.commit()
    await db.refresh(task)
    return serialize_task(task)


@router.post("/{task_id}/stop", response_model=TaskResponse)
async def stop_task(
    task_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TaskResponse:
    task = await get_user_task(db, current_user, task_id)
    if task.status not in {TaskStatus.PENDING, TaskStatus.RUNNING}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="只有待执行或运行中的任务可以停止。",
        )

    task.status = TaskStatus.CANCELLED
    task.finished_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(task)
    return serialize_task(task)


@router.delete("/{task_id}")
async def delete_task(
    task_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    task = await get_user_task(db, current_user, task_id)
    if task.status == TaskStatus.RUNNING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="运行中的任务不能删除，请先停止任务。",
        )

    await db.delete(task)
    await db.commit()
    return {"ok": True}
