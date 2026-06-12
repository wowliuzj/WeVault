import mimetypes
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import FileResponse, Response

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.article import Article, ArticleContent
from app.models.enums import FetchStatus, TaskStatus, TaskType
from app.models.task import CollectionTask
from app.models.user import User
from app.models.wechat import WechatSource
from app.services.article_assets import (
    ArticleAssetError,
    cache_article_cover,
    get_article_content_asset_file,
    get_article_cover_file,
    is_allowed_wechat_image_url,
    normalize_image_url,
)
from app.services.wechat_login_driver import MP_HEADERS

router = APIRouter()


class ArticleSourceResponse(BaseModel):
    id: str
    name: str
    avatar_url: str | None = None
    avatar_asset_url: str | None = None


class ArticleResponse(BaseModel):
    id: str
    title: str
    author: str | None = None
    digest: str | None = None
    cover_url: str | None = None
    cover_asset_url: str | None = None
    original_url: str
    publish_time: datetime | None = None
    content_status: str
    deleted_at: datetime | None = None
    source: ArticleSourceResponse
    created_at: datetime
    updated_at: datetime


class ArticleListResponse(BaseModel):
    items: list[ArticleResponse]
    total: int
    page: int
    page_size: int


class ArticleSummaryResponse(BaseModel):
    total: int
    content_fetched: int
    recent: list[ArticleResponse]


class ArticleDetailResponse(ArticleResponse):
    content_clean_html: str | None = None
    content_plain_text: str | None = None
    content_markdown: str | None = None
    content_fetched_at: datetime | None = None


class ArticleBatchRequest(BaseModel):
    article_ids: list[UUID] = Field(min_length=1)


def source_avatar_asset_url(source: WechatSource) -> str | None:
    if not source.avatar_storage_path:
        return None
    return f"/api/v1/sources/{source.id}/avatar"


def article_cover_asset_url(article: Article) -> str | None:
    if not article.cover_storage_path:
        return None
    return f"/api/v1/articles/{article.id}/cover"


def serialize_article(article: Article, source: WechatSource) -> ArticleResponse:
    return ArticleResponse(
        id=str(article.id),
        title=article.title,
        author=article.author,
        digest=article.digest,
        cover_url=normalize_image_url(article.cover_url),
        cover_asset_url=article_cover_asset_url(article),
        original_url=article.original_url,
        publish_time=article.publish_time,
        content_status=article.content_status.value,
        deleted_at=article.deleted_at,
        source=ArticleSourceResponse(
            id=str(source.id),
            name=source.name,
            avatar_url=source.avatar_url,
            avatar_asset_url=source_avatar_asset_url(source),
        ),
        created_at=article.created_at,
        updated_at=article.updated_at,
    )


async def get_user_article(
    db: AsyncSession,
    user: User,
    article_id: UUID,
) -> tuple[Article, WechatSource]:
    result = await db.execute(
        select(Article, WechatSource)
        .join(WechatSource, Article.source_id == WechatSource.id)
        .where(
            Article.id == article_id,
            Article.user_id == user.id,
            Article.deleted_at.is_(None),
            WechatSource.deleted_at.is_(None),
        )
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="文章不存在。",
        )
    return row


async def validate_user_articles(
    db: AsyncSession,
    user: User,
    article_ids: list[UUID],
    *,
    deleted: bool = False,
) -> list[Article]:
    deleted_condition = Article.deleted_at.is_not(None) if deleted else Article.deleted_at.is_(None)
    result = await db.execute(
        select(Article).join(WechatSource, Article.source_id == WechatSource.id).where(
            Article.user_id == user.id,
            Article.id.in_(article_ids),
            deleted_condition,
            WechatSource.deleted_at.is_(None),
        )
    )
    articles = list(result.scalars().all())
    if len(articles) != len(set(article_ids)):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="部分文章不存在。",
        )
    return articles


@router.get("", response_model=ArticleListResponse)
async def list_articles(
    keyword: str | None = Query(default=None, max_length=120),
    source_id: UUID | None = None,
    deleted: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=5, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ArticleListResponse:
    conditions = [
        Article.user_id == current_user.id,
        Article.deleted_at.is_not(None) if deleted else Article.deleted_at.is_(None),
        WechatSource.deleted_at.is_(None),
    ]
    if source_id is not None:
        conditions.append(Article.source_id == source_id)
    if keyword:
        pattern = f"%{keyword.strip()}%"
        conditions.append(
            or_(
                Article.title.ilike(pattern),
                Article.author.ilike(pattern),
                Article.digest.ilike(pattern),
                WechatSource.name.ilike(pattern),
            )
        )

    total_result = await db.execute(
        select(func.count())
        .select_from(Article)
        .join(WechatSource, Article.source_id == WechatSource.id)
        .where(*conditions)
    )
    total = int(total_result.scalar_one())
    offset = (page - 1) * page_size
    rows = await db.execute(
        select(Article, WechatSource)
        .join(WechatSource, Article.source_id == WechatSource.id)
        .where(*conditions)
        .order_by(
            Article.deleted_at.desc().nullslast()
            if deleted
            else Article.publish_time.desc().nullslast(),
            Article.created_at.desc(),
        )
        .offset(offset)
        .limit(page_size)
    )
    return ArticleListResponse(
        items=[serialize_article(article, source) for article, source in rows.all()],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/summary", response_model=ArticleSummaryResponse)
async def get_article_summary(
    limit: int = Query(default=5, ge=1, le=20),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ArticleSummaryResponse:
    conditions = [
        Article.user_id == current_user.id,
        Article.deleted_at.is_(None),
        WechatSource.deleted_at.is_(None),
    ]
    total_result = await db.execute(
        select(func.count())
        .select_from(Article)
        .join(WechatSource, Article.source_id == WechatSource.id)
        .where(*conditions)
    )
    fetched_result = await db.execute(
        select(func.count())
        .select_from(Article)
        .join(WechatSource, Article.source_id == WechatSource.id)
        .where(*conditions, Article.content_status == FetchStatus.FETCHED)
    )
    recent_rows = await db.execute(
        select(Article, WechatSource)
        .join(WechatSource, Article.source_id == WechatSource.id)
        .where(*conditions)
        .order_by(Article.publish_time.desc().nullslast(), Article.created_at.desc())
        .limit(limit)
    )
    return ArticleSummaryResponse(
        total=int(total_result.scalar_one()),
        content_fetched=int(fetched_result.scalar_one()),
        recent=[serialize_article(article, source) for article, source in recent_rows.all()],
    )


@router.get("/cover")
async def proxy_article_cover(url: str) -> Response:
    cover_url = normalize_image_url(url)
    if not cover_url or not is_allowed_wechat_image_url(cover_url):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported cover URL",
        )

    try:
        async with httpx.AsyncClient(
            headers=MP_HEADERS,
            timeout=httpx.Timeout(12.0, connect=6.0),
            follow_redirects=True,
        ) as client:
            response = await client.get(cover_url)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="读取文章封面失败",
        ) from exc

    return Response(
        content=response.content,
        media_type=response.headers.get("content-type", "image/jpeg").split(";")[0],
        headers={"Cache-Control": "public, max-age=86400"},
    )


async def create_article_task(
    db: AsyncSession,
    user: User,
    article_ids: list[UUID],
    task_type: TaskType,
) -> CollectionTask:
    articles = await validate_user_articles(db, user, article_ids)
    task = CollectionTask(
        user_id=user.id,
        task_type=task_type,
        status=TaskStatus.PENDING,
        progress_current=0,
        progress_total=len(articles),
        retry_count=0,
        target_type="article_batch",
        target_id=None,
        payload={
            "article_ids": [str(article.id) for article in articles],
            "run_mode": "immediate",
        },
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


@router.post("/fetch-content")
async def fetch_article_content(
    payload: ArticleBatchRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    task = await create_article_task(
        db,
        current_user,
        payload.article_ids,
        TaskType.FETCH_ARTICLE_CONTENT,
    )
    return {"status": "queued", "task_id": str(task.id)}


@router.post("/batch-delete")
async def delete_articles(
    payload: ArticleBatchRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    articles = await validate_user_articles(db, current_user, payload.article_ids)
    deleted_at = datetime.now(UTC)
    for article in articles:
        article.deleted_at = deleted_at
    await db.commit()
    return {"deleted": len(articles)}


@router.post("/batch-restore")
async def restore_articles(
    payload: ArticleBatchRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    articles = await validate_user_articles(db, current_user, payload.article_ids, deleted=True)
    for article in articles:
        article.deleted_at = None
    await db.commit()
    return {"restored": len(articles)}


@router.post("/{article_id}/restore", response_model=ArticleResponse)
async def restore_article(
    article_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ArticleResponse:
    articles = await validate_user_articles(db, current_user, [article_id], deleted=True)
    article = articles[0]
    article.deleted_at = None
    await db.commit()
    await db.refresh(article)
    _, source = await get_user_article(db, current_user, article.id)
    return serialize_article(article, source)


@router.get("/{article_id}/cover")
async def get_cached_article_cover(
    article_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    result = await db.execute(
        select(Article).where(Article.id == article_id)
    )
    article = result.scalar_one_or_none()
    if article is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Article cover not found",
        )
    try:
        cover_file = get_article_cover_file(article)
    except ArticleAssetError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return FileResponse(
        cover_file,
        media_type=article.cover_content_type or "image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/{article_id}/assets/{asset_name}")
async def get_cached_article_asset(
    article_id: UUID,
    asset_name: str,
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    result = await db.execute(
        select(Article).where(Article.id == article_id)
    )
    article = result.scalar_one_or_none()
    if article is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Article asset not found",
        )

    try:
        asset_file = get_article_content_asset_file(article, asset_name)
    except ArticleAssetError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return FileResponse(
        asset_file,
        media_type=mimetypes.guess_type(asset_name)[0] or "application/octet-stream",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/{article_id}", response_model=ArticleDetailResponse)
async def get_article(
    article_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ArticleDetailResponse:
    article, source = await get_user_article(db, current_user, article_id)
    content_result = await db.execute(
        select(ArticleContent).where(ArticleContent.article_id == article.id)
    )
    content = content_result.scalar_one_or_none()
    response = serialize_article(article, source).model_dump()
    response.update(
        {
            "content_plain_text": content.plain_text if content else None,
            "content_clean_html": content.clean_html if content else None,
            "content_markdown": content.markdown if content else None,
            "content_fetched_at": content.fetched_at if content else None,
        }
    )
    return ArticleDetailResponse(**response)


@router.post("/{article_id}/refresh", response_model=ArticleResponse)
async def refresh_article(
    article_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ArticleResponse:
    article, source = await get_user_article(db, current_user, article_id)
    await cache_article_cover(article)
    article.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(article)
    return serialize_article(article, source)


@router.delete("/{article_id}")
async def delete_article(
    article_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    article, _ = await get_user_article(db, current_user, article_id)
    article.deleted_at = datetime.now(UTC)
    await db.commit()
    return {"ok": True}
