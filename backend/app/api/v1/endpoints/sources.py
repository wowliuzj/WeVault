from datetime import datetime
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import FileResponse, Response

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.enums import SourceStatus
from app.models.user import User
from app.models.wechat import WechatSource
from app.services.sources import (
    SourceServiceError,
    add_source_from_article_url,
    add_source_from_search,
    delete_source_tree,
    get_source_avatar_file,
    is_allowed_avatar_url,
    list_user_sources,
    refresh_source_info,
    search_wechat_sources,
    to_http_error,
    update_source_auto_fetch,
    update_source_status,
)
from app.services.wechat_login_driver import MP_HEADERS

router = APIRouter()


class SourceResponse(BaseModel):
    id: str
    name: str
    alias: str | None = None
    fakeid: str | None = None
    biz: str | None = None
    avatar_url: str | None = None
    avatar_asset_url: str | None = None
    description: str | None = None
    source_from: str
    status: str
    auto_fetch_content: bool
    auto_fetch_enabled: bool
    auto_fetch_last_scheduled_at: datetime | None = None
    last_article_at: datetime | None = None
    last_list_fetched_at: datetime | None = None
    last_content_fetched_at: datetime | None = None
    article_count: int


class SourceSearchRequest(BaseModel):
    keyword: str = Field(min_length=1, max_length=80)
    begin: int = Field(default=0, ge=0)
    count: int = Field(default=5, ge=1, le=20)


class SourceSearchItem(BaseModel):
    name: str
    alias: str | None = None
    fakeid: str | None = None
    biz: str | None = None
    avatar_url: str | None = None
    description: str | None = None
    raw_data: dict[str, Any] | None = None
    already_added: bool = False


class SourceSearchResponse(BaseModel):
    keyword: str
    items: list[SourceSearchItem]


class SourceFromSearchRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    alias: str | None = None
    fakeid: str = Field(min_length=1, max_length=160)
    biz: str | None = None
    avatar_url: str | None = None
    description: str | None = None
    raw_data: dict[str, Any] | None = None


class SourceFromUrlRequest(BaseModel):
    article_url: str = Field(min_length=8, max_length=2000)


class SourceStatusRequest(BaseModel):
    status: Literal[SourceStatus.ACTIVE, SourceStatus.PAUSED]


class SourceAutoFetchRequest(BaseModel):
    enabled: bool


@router.get("/avatar")
async def proxy_source_avatar(url: str) -> Response:
    if not is_allowed_avatar_url(url):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported avatar URL",
        )

    try:
        async with httpx.AsyncClient(
            headers=MP_HEADERS,
            timeout=httpx.Timeout(12.0, connect=6.0),
            follow_redirects=True,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="读取公众号头像失败",
        ) from exc

    return Response(
        content=response.content,
        media_type=response.headers.get("content-type", "image/jpeg").split(";")[0],
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/{source_id}/avatar")
async def get_cached_source_avatar(
    source_id: str,
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    result = await db.execute(select(WechatSource).where(WechatSource.id == source_id))
    source = result.scalar_one_or_none()
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Source avatar not found",
        )

    try:
        avatar_file = get_source_avatar_file(source)
    except SourceServiceError as exc:
        raise to_http_error(exc) from exc

    return FileResponse(
        avatar_file,
        media_type=source.avatar_content_type or "image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("", response_model=list[SourceResponse])
async def list_sources(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    return await list_user_sources(db, current_user)


@router.post("/search", response_model=SourceSearchResponse)
async def search_sources(
    payload: SourceSearchRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        items = await search_wechat_sources(
            db,
            current_user,
            payload.keyword.strip(),
            payload.begin,
            payload.count,
        )
    except SourceServiceError as exc:
        raise to_http_error(exc) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="连接微信公众平台失败，请检查网络或代理后重试。",
        ) from exc
    return {"keyword": payload.keyword, "items": items}


@router.post("", response_model=SourceResponse)
async def create_source_from_search(
    payload: SourceFromSearchRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        return await add_source_from_search(db, current_user, payload.model_dump())
    except SourceServiceError as exc:
        raise to_http_error(exc) from exc


@router.post("/from-article-url", response_model=SourceResponse)
async def create_source_from_article_url(
    payload: SourceFromUrlRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        return await add_source_from_article_url(db, current_user, payload.article_url.strip())
    except SourceServiceError as exc:
        raise to_http_error(exc) from exc


@router.post("/{source_id}/refresh", response_model=SourceResponse)
async def refresh_source(
    source_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        return await refresh_source_info(db, current_user, source_id)
    except SourceServiceError as exc:
        raise to_http_error(exc) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="连接微信公众平台失败，请检查网络或代理后重试。",
        ) from exc


@router.patch("/{source_id}/status", response_model=SourceResponse)
async def update_source_state(
    source_id: str,
    payload: SourceStatusRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        return await update_source_status(db, current_user, source_id, payload.status)
    except SourceServiceError as exc:
        raise to_http_error(exc) from exc


@router.api_route(
    "/{source_id}/auto-fetch",
    methods=["PATCH", "POST"],
    response_model=SourceResponse,
)
async def update_source_auto_fetch_state(
    source_id: str,
    payload: SourceAutoFetchRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        return await update_source_auto_fetch(db, current_user, source_id, payload.enabled)
    except SourceServiceError as exc:
        raise to_http_error(exc) from exc


@router.post("/{source_id}/pause", response_model=SourceResponse)
async def pause_source(
    source_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        return await update_source_status(db, current_user, source_id, SourceStatus.PAUSED)
    except SourceServiceError as exc:
        raise to_http_error(exc) from exc


@router.post("/{source_id}/resume", response_model=SourceResponse)
async def resume_source(
    source_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        return await update_source_status(db, current_user, source_id, SourceStatus.ACTIVE)
    except SourceServiceError as exc:
        raise to_http_error(exc) from exc


@router.delete("/{source_id}")
async def delete_source(
    source_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    try:
        await delete_source_tree(db, current_user, source_id)
    except SourceServiceError as exc:
        raise to_http_error(exc) from exc
    return {"ok": True}


@router.post("/{source_id}/sync-list")
async def sync_source_article_list(source_id: str) -> dict[str, str]:
    return {
        "status": "queued",
        "task_type": "fetch_source_articles",
        "source_id": source_id,
    }
