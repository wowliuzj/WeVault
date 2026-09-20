import secrets
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.models.article import Article, ArticleContent
from app.models.wechat import WechatSource
from app.services.article_assets import normalize_image_url

router = APIRouter()
bearer_scheme = HTTPBearer(auto_error=False)


class ExternalArticleSourceResponse(BaseModel):
    id: str
    name: str


class ExternalArticleResponse(BaseModel):
    id: str
    title: str
    author: str | None = None
    digest: str | None = None
    cover_url: str | None = None
    original_url: str
    publish_time: datetime | None = None
    source: ExternalArticleSourceResponse
    content: str | None = None


class ExternalArticlePaginationResponse(BaseModel):
    page: int
    page_size: int
    total_count: int
    item_count: int


class ExternalArticleListResponse(BaseModel):
    items: list[ExternalArticleResponse]
    pagination: ExternalArticlePaginationResponse


async def require_robottoday_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> None:
    configured_token = settings.robottoday_token
    if not configured_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="External article API token is not configured",
        )
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not secrets.compare_digest(credentials.credentials, configured_token)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


def build_date_range(
    start_date: date | None,
    end_date: date | None,
) -> tuple[datetime | None, datetime | None]:
    if start_date is not None and end_date is not None and end_date < start_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="end_date must be greater than or equal to start_date",
        )

    start_at = datetime.combine(start_date, time.min, tzinfo=UTC) if start_date else None
    end_before = (
        datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=UTC)
        if end_date
        else None
    )
    return start_at, end_before


def serialize_external_article(
    article: Article,
    source: WechatSource,
    article_content: str | None = None,
    *,
    include_content: bool,
) -> ExternalArticleResponse:
    payload = {
        "id": str(article.id),
        "title": article.title,
        "author": article.author,
        "digest": article.digest,
        "cover_url": normalize_image_url(article.cover_url),
        "original_url": article.original_url,
        "publish_time": article.publish_time,
        "source": ExternalArticleSourceResponse(id=str(source.id), name=source.name),
    }
    if include_content:
        payload["content"] = article_content
    return ExternalArticleResponse(**payload)


@router.post(
    "/articles",
    response_model=ExternalArticleListResponse,
    response_model_exclude_unset=True,
    dependencies=[Depends(require_robottoday_token)],
)
async def list_external_articles(
    source_id: UUID = Form(...),
    page: int = Form(default=1, ge=1),
    page_size: int = Form(default=20, ge=1, le=100),
    content: bool = Form(default=True),
    start_date: date | None = Form(default=None),
    end_date: date | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
) -> ExternalArticleListResponse:
    start_at, end_before = build_date_range(start_date, end_date)
    conditions = [
        Article.source_id == source_id,
        Article.deleted_at.is_(None),
        WechatSource.deleted_at.is_(None),
    ]
    if start_at is not None:
        conditions.append(Article.publish_time >= start_at)
    if end_before is not None:
        conditions.append(Article.publish_time < end_before)

    total_result = await db.execute(
        select(func.count())
        .select_from(Article)
        .join(WechatSource, Article.source_id == WechatSource.id)
        .where(*conditions)
    )
    total_count = int(total_result.scalar_one())

    query = (
        select(Article, WechatSource)
        .join(WechatSource, Article.source_id == WechatSource.id)
        .where(*conditions)
        .order_by(Article.publish_time.desc().nullslast(), Article.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    if content:
        query = query.add_columns(ArticleContent.clean_html).outerjoin(
            ArticleContent,
            ArticleContent.article_id == Article.id,
        )

    rows = (await db.execute(query)).all()
    items = [
        serialize_external_article(
            row[0],
            row[1],
            row[2] if content else None,
            include_content=content,
        )
        for row in rows
    ]
    return ExternalArticleListResponse(
        items=items,
        pagination=ExternalArticlePaginationResponse(
            page=page,
            page_size=page_size,
            total_count=total_count,
            item_count=len(items),
        ),
    )
