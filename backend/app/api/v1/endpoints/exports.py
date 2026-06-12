from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class ExportJobResponse(BaseModel):
    id: str
    name: str
    format: str
    status: str
    note: str


class CreateExportRequest(BaseModel):
    name: str
    format: str
    article_ids: list[str]


@router.get("", response_model=list[ExportJobResponse])
async def list_export_jobs() -> list[ExportJobResponse]:
    return [
        ExportJobResponse(
            id="export-product-pdf",
            name="产品笔记精选 24 篇",
            format="pdf",
            status="succeeded",
            note="PDF · 保留文本 · 28.4 MB",
        ),
        ExportJobResponse(
            id="export-kb-docx",
            name="企业知识库专题",
            format="docx",
            status="succeeded",
            note="DOCX · 16 篇文章 · 12.1 MB",
        ),
    ]


@router.post("")
async def create_export_job(payload: CreateExportRequest) -> dict[str, object]:
    return {
        "status": "queued",
        "task_type": "export_articles",
        "name": payload.name,
        "format": payload.format,
        "article_ids": payload.article_ids,
    }
