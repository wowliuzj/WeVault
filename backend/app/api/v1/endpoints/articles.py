from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class ArticleResponse(BaseModel):
    id: str
    title: str
    source: str
    published_at: str
    content_status: str
    comment_status: str


class ArticleBatchRequest(BaseModel):
    article_ids: list[str]


@router.get("", response_model=list[ArticleResponse])
async def list_articles() -> list[ArticleResponse]:
    return [
        ArticleResponse(
            id="article-ai-pm",
            title="AI 产品经理的长期主义",
            source="产品笔记",
            published_at="2026-06-09",
            content_status="fetched",
            comment_status="fetched",
        ),
        ArticleResponse(
            id="article-kb",
            title="一文讲清企业知识库落地",
            source="技术观察站",
            published_at="2026-06-08",
            content_status="pending",
            comment_status="pending",
        ),
    ]


@router.post("/fetch-content")
async def fetch_article_content(payload: ArticleBatchRequest) -> dict[str, object]:
    return {
        "status": "queued",
        "task_type": "fetch_article_content",
        "article_ids": payload.article_ids,
    }


@router.post("/fetch-comments")
async def fetch_article_comments(payload: ArticleBatchRequest) -> dict[str, object]:
    return {
        "status": "queued",
        "task_type": "fetch_article_comments",
        "article_ids": payload.article_ids,
    }

