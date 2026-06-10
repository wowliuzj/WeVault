from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class TaskResponse(BaseModel):
    id: str
    task_type: str
    status: str
    progress_current: int
    progress_total: int
    note: str


@router.get("", response_model=list[TaskResponse])
async def list_tasks() -> list[TaskResponse]:
    return [
        TaskResponse(
            id="task-content",
            task_type="fetch_article_content",
            status="running",
            progress_current=12,
            progress_total=40,
            note="技术观察站 · 12/40",
        ),
        TaskResponse(
            id="task-list",
            task_type="fetch_source_articles",
            status="succeeded",
            progress_current=120,
            progress_total=120,
            note="产品笔记 · 完成",
        ),
    ]

