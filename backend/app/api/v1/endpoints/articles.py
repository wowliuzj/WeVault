import mimetypes
import re
from datetime import UTC, datetime
from html import unescape
from typing import Any, Literal
from urllib.parse import parse_qs, urlparse
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
from app.models.enums import FetchStatus, SourceFrom, SourceStatus, TaskStatus, TaskType
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
from app.services.article_fetcher import (
    article_headers,
    decode_js_string,
    extract_js_value,
    extract_meta_content,
)
from app.services.sources import (
    SourceServiceError,
    cache_source_avatar,
    get_active_authorized_session,
    resolve_search_metadata_for_article_source,
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


class ArticleFromUrlRequest(BaseModel):
    article_url: str = Field(min_length=8, max_length=2000)
    fetch_content: bool = True


class ArticleFromUrlResponse(BaseModel):
    status: Literal["created", "existing"]
    article: ArticleResponse
    task_id: str | None = None


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


def decode_extracted_value(value: str | None) -> str | None:
    if not value:
        return None
    decoded = unescape(decode_js_string(value)).strip()
    return decoded or None


def parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    value = value.strip()
    return int(value) if value.isdigit() else None


def extract_query_value(url: str, *names: str) -> str | None:
    query = parse_qs(urlparse(url).query)
    for name in names:
        value = (query.get(name) or [None])[0]
        if value:
            return value
    return None


def extract_source_name(page_html: str) -> str | None:
    nickname = decode_extracted_value(extract_js_value(page_html, "nickname"))
    if nickname:
        return nickname
    match = re.search(
        r'class="[^"]*wx_follow_nickname[^"]*"[^>]*>(?P<name>[^<]+)<',
        page_html,
    )
    if not match:
        return None
    return unescape(match.group("name")).strip() or None


def parse_article_publish_time(page_html: str) -> datetime | None:
    ct = parse_int(extract_js_value(page_html, "ct"))
    if ct:
        return datetime.fromtimestamp(ct, tz=UTC)

    publish_time = decode_extracted_value(extract_js_value(page_html, "publish_time"))
    if not publish_time:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(publish_time, fmt)
            return parsed.replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def parse_article_from_html(article_url: str, page_html: str) -> dict[str, Any]:
    resolved_url = article_url
    biz = extract_query_value(resolved_url, "__biz", "biz") or decode_extracted_value(
        extract_js_value(page_html, "biz")
    )
    appmsgid = extract_query_value(resolved_url, "mid", "appmsgid") or decode_extracted_value(
        extract_js_value(page_html, "appmsgid")
    )
    itemidx = parse_int(extract_query_value(resolved_url, "idx", "itemidx")) or parse_int(
        extract_js_value(page_html, "idx")
    )
    if appmsgid and itemidx is None:
        itemidx = 1

    title = (
        extract_meta_content(page_html, "og:title")
        or decode_extracted_value(extract_js_value(page_html, "msg_title"))
        or "未命名文章"
    )
    digest = extract_meta_content(page_html, "og:description") or decode_extracted_value(
        extract_js_value(page_html, "msg_desc")
    )
    cover_url = extract_meta_content(page_html, "og:image") or decode_extracted_value(
        extract_js_value(page_html, "msg_cdn_url")
    )

    return {
        "source": {
            "name": extract_source_name(page_html) or "待识别公众号",
            "alias": decode_extracted_value(extract_js_value(page_html, "user_name")),
            "biz": biz,
            "avatar_url": decode_extracted_value(extract_js_value(page_html, "round_head_img"))
            or decode_extracted_value(extract_js_value(page_html, "head_img"))
            or decode_extracted_value(extract_js_value(page_html, "hd_head_img"))
            or decode_extracted_value(extract_js_value(page_html, "ori_head_img_url"))
            or decode_extracted_value(extract_js_value(page_html, "ori_head_img")),
            "description": (
                decode_extracted_value(extract_js_value(page_html, "profile_signature_new"))
                or decode_extracted_value(extract_js_value(page_html, "profile_signature"))
                or decode_extracted_value(extract_js_value(page_html, "signature"))
            ),
        },
        "article": {
            "title": title,
            "author": extract_meta_content(page_html, "og:article:author")
            or decode_extracted_value(extract_js_value(page_html, "author")),
            "digest": digest,
            "cover_url": cover_url,
            "original_url": resolved_url,
            "publish_time": parse_article_publish_time(page_html),
            "msgid": appmsgid,
            "idx": itemidx,
            "biz": biz,
            "appmsgid": appmsgid,
            "itemidx": itemidx,
            "raw_data": {"article_url": resolved_url, "source": "article_url"},
        },
    }


async def fetch_article_metadata_from_url(
    article_url: str,
    cookies: list[dict[str, Any]],
) -> dict[str, Any]:
    parsed = urlparse(article_url)
    if parsed.netloc not in {"mp.weixin.qq.com", "mp.weixin.qq.com.cn"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请粘贴 mp.weixin.qq.com 的公众号文章链接。",
        )

    try:
        async with httpx.AsyncClient(
            headers=article_headers(cookies),
            timeout=httpx.Timeout(25.0, connect=10.0),
            follow_redirects=True,
        ) as client:
            response = await client.get(article_url)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="读取文章链接失败，请检查链接是否可访问。",
        ) from exc

    return parse_article_from_html(str(response.url), response.text)


async def get_or_create_paused_source_for_article(
    db: AsyncSession,
    user: User,
    wechat_account_id: UUID,
    source_data: dict[str, Any],
    article_url: str,
) -> WechatSource:
    matched = await resolve_search_metadata_for_article_source(db, user, source_data)
    source_payload = {**source_data, **(matched or {})}
    biz = source_payload.get("biz") or source_data.get("biz")
    if not biz:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="文章链接中没有解析到公众号 biz。",
        )

    result = await db.execute(
        select(WechatSource).where(
            WechatSource.user_id == user.id,
            WechatSource.biz == biz,
        )
    )
    source = result.scalar_one_or_none()
    if source is None:
        source = WechatSource(
            user_id=user.id,
            wechat_account_id=wechat_account_id,
            name=source_payload.get("name") or "待识别公众号",
            alias=source_payload.get("alias"),
            fakeid=source_payload.get("fakeid"),
            biz=biz,
            avatar_url=source_payload.get("avatar_url"),
            description=source_payload.get("description"),
            source_from=SourceFrom.ARTICLE_URL,
            status=SourceStatus.PAUSED,
            raw_data={"article_url": article_url},
        )
        db.add(source)
        await db.flush()
    else:
        source.wechat_account_id = wechat_account_id
        source.name = source_payload.get("name") or source.name
        source.alias = source_payload.get("alias") or source.alias
        source.fakeid = source_payload.get("fakeid") or source.fakeid
        source.avatar_url = source_payload.get("avatar_url") or source.avatar_url
        source.description = source_payload.get("description") or source.description
        source.deleted_at = None
        if source.status == SourceStatus.FAILED:
            source.status = SourceStatus.PAUSED
        source.raw_data = {**(source.raw_data or {}), "article_url": article_url}

    await cache_source_avatar(source)
    return source


async def find_existing_article(
    db: AsyncSession,
    user: User,
    source: WechatSource,
    article_data: dict[str, Any],
) -> Article | None:
    appmsgid = article_data.get("appmsgid")
    itemidx = article_data.get("itemidx")
    if appmsgid and itemidx is not None:
        result = await db.execute(
            select(Article).where(
                Article.user_id == user.id,
                Article.source_id == source.id,
                Article.appmsgid == appmsgid,
                Article.itemidx == itemidx,
            )
        )
        article = result.scalar_one_or_none()
        if article is not None:
            return article

    result = await db.execute(
        select(Article).where(
            Article.user_id == user.id,
            Article.original_url == article_data["original_url"],
        )
    )
    return result.scalar_one_or_none()


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


@router.post("/from-url", response_model=ArticleFromUrlResponse)
async def create_article_from_url(
    payload: ArticleFromUrlRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ArticleFromUrlResponse:
    try:
        account, _, cookies, _ = await get_active_authorized_session(db, current_user)
    except SourceServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    metadata = await fetch_article_metadata_from_url(payload.article_url.strip(), cookies)
    source = await get_or_create_paused_source_for_article(
        db,
        current_user,
        account.id,
        metadata["source"],
        metadata["article"]["original_url"],
    )
    article_data = metadata["article"]
    existing_article = await find_existing_article(db, current_user, source, article_data)
    if existing_article is not None:
        await db.commit()
        existing_source = source
        if existing_article.source_id != source.id:
            source_result = await db.execute(
                select(WechatSource).where(WechatSource.id == existing_article.source_id)
            )
            existing_source = source_result.scalar_one_or_none() or source
        return ArticleFromUrlResponse(
            status="existing",
            article=serialize_article(existing_article, existing_source),
        )

    article = Article(
        user_id=current_user.id,
        source_id=source.id,
        wechat_account_id=account.id,
        title=article_data["title"],
        author=article_data["author"],
        digest=article_data["digest"],
        cover_url=article_data["cover_url"],
        original_url=article_data["original_url"],
        publish_time=article_data["publish_time"],
        msgid=article_data["msgid"],
        idx=article_data["idx"],
        biz=article_data["biz"],
        appmsgid=article_data["appmsgid"],
        itemidx=article_data["itemidx"],
        content_status=FetchStatus.PENDING,
        raw_data=article_data["raw_data"],
    )
    db.add(article)
    await db.flush()
    await cache_article_cover(article, cookies=cookies)
    await db.commit()
    await db.refresh(article)
    await db.refresh(source)

    task_id = None
    if payload.fetch_content:
        task = await create_article_task(
            db,
            current_user,
            [article.id],
            TaskType.FETCH_ARTICLE_CONTENT,
        )
        task_id = str(task.id)

    return ArticleFromUrlResponse(
        status="created",
        article=serialize_article(article, source),
        task_id=task_id,
    )


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
