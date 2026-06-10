from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class SourceResponse(BaseModel):
    id: str
    name: str
    note: str
    auto_fetch_content: bool
    auto_fetch_comments: bool


class SourceSearchRequest(BaseModel):
    keyword: str


class SourceFromUrlRequest(BaseModel):
    article_url: str


@router.get("", response_model=list[SourceResponse])
async def list_sources() -> list[SourceResponse]:
    return [
        SourceResponse(
            id="source-product",
            name="产品笔记",
            note="18,642 篇文章 · 自动正文开启 · 自动评论关闭",
            auto_fetch_content=True,
            auto_fetch_comments=False,
        ),
        SourceResponse(
            id="source-tech",
            name="技术观察站",
            note="7,104 篇文章 · 自动正文关闭 · 自动评论关闭",
            auto_fetch_content=False,
            auto_fetch_comments=False,
        ),
    ]


@router.post("/search")
async def search_sources(payload: SourceSearchRequest) -> dict[str, object]:
    return {
        "keyword": payload.keyword,
        "items": [],
    }


@router.post("/from-article-url")
async def create_source_from_article_url(payload: SourceFromUrlRequest) -> dict[str, str]:
    return {
        "status": "queued",
        "article_url": payload.article_url,
    }


@router.post("/{source_id}/sync-list")
async def sync_source_article_list(source_id: str) -> dict[str, str]:
    return {
        "status": "queued",
        "task_type": "fetch_source_articles",
        "source_id": source_id,
    }

