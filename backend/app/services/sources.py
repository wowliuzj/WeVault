from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.article import Article
from app.models.enums import SourceFrom, SourceStatus, TokenStatus
from app.models.user import User
from app.models.wechat import WechatAccount, WechatSession, WechatSource
from app.services.wechat_login_driver import MP_BASE_URL, MP_HEADERS, wechat_login_manager


class SourceServiceError(RuntimeError):
    pass


IMAGE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


def _normalize_search_item(item: dict[str, Any]) -> dict[str, Any]:
    avatar_url = item.get("round_head_img") or item.get("head_img") or item.get("avatar_url")
    return {
        "name": item.get("nickname") or item.get("name") or "未命名公众号",
        "alias": item.get("alias"),
        "fakeid": item.get("fakeid"),
        "biz": item.get("__biz") or item.get("biz"),
        "avatar_url": _normalize_avatar_url(avatar_url),
        "description": item.get("signature") or item.get("desc"),
        "raw_data": item,
    }


def _normalize_avatar_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    avatar_url = unescape(value).strip()
    if not avatar_url:
        return None
    if avatar_url.startswith("//"):
        return f"https:{avatar_url}"
    if avatar_url.startswith("http://"):
        return f"https://{avatar_url.removeprefix('http://')}"
    return avatar_url


def is_allowed_avatar_url(value: str) -> bool:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        return False
    hostname = parsed.hostname or ""
    return (
        hostname == "mp.weixin.qq.com"
        or hostname.endswith(".qpic.cn")
        or hostname.endswith(".qlogo.cn")
    )


def get_source_avatar_file(source: WechatSource) -> Path:
    if not source.avatar_storage_path:
        raise SourceServiceError("公众号源还没有本地头像缓存。")

    storage_root = Path(settings.asset_storage_dir).resolve()
    avatar_file = (storage_root / source.avatar_storage_path).resolve()
    if not avatar_file.is_relative_to(storage_root):
        raise SourceServiceError("头像缓存路径异常。")
    if not avatar_file.is_file():
        raise SourceServiceError("公众号本地头像文件不存在，请先刷新公众号信息。")
    return avatar_file


async def cache_source_avatar(source: WechatSource) -> None:
    avatar_url = _normalize_avatar_url(source.avatar_url)
    if not avatar_url or not is_allowed_avatar_url(avatar_url):
        return

    try:
        async with httpx.AsyncClient(
            headers=MP_HEADERS,
            timeout=httpx.Timeout(12.0, connect=6.0),
            follow_redirects=True,
        ) as client:
            response = await client.get(avatar_url)
            response.raise_for_status()
    except httpx.HTTPError:
        return

    content_type = response.headers.get("content-type", "image/jpeg").split(";")[0]
    if not content_type.startswith("image/") or len(response.content) > 2 * 1024 * 1024:
        return

    extension = IMAGE_EXTENSIONS.get(content_type, ".jpg")
    relative_path = Path("source-avatars") / f"{source.id}{extension}"
    avatar_file = Path(settings.asset_storage_dir) / relative_path
    avatar_file.parent.mkdir(parents=True, exist_ok=True)
    avatar_file.write_bytes(response.content)

    source.avatar_storage_path = relative_path.as_posix()
    source.avatar_content_type = content_type


def _extract_account_name(page_html: str) -> str | None:
    match = re.search(
        r'class="[^"]*wx_follow_nickname[^"]*"[^>]*>(?P<name>[^<]+)<',
        page_html,
    )
    if not match:
        return None
    name = unescape(match.group("name")).strip()
    return name or None


def _serialize_source(
    source: WechatSource,
    *,
    article_count: int = 0,
    last_article_at: datetime | None = None,
) -> dict[str, Any]:
    return {
        "id": str(source.id),
        "name": source.name,
        "alias": source.alias,
        "fakeid": source.fakeid,
        "biz": source.biz,
        "avatar_url": _normalize_avatar_url(source.avatar_url),
        "avatar_asset_url": f"/api/v1/sources/{source.id}/avatar"
        if source.avatar_storage_path
        else None,
        "description": source.description,
        "source_from": source.source_from.value,
        "status": source.status.value,
        "auto_fetch_content": source.auto_fetch_content,
        "auto_fetch_enabled": source.auto_fetch_enabled,
        "auto_fetch_last_scheduled_at": source.auto_fetch_last_scheduled_at,
        "last_article_at": last_article_at,
        "last_list_fetched_at": source.last_list_fetched_at,
        "last_content_fetched_at": source.last_content_fetched_at,
        "article_count": article_count,
    }


async def get_active_authorized_session(
    db: AsyncSession,
    user: User,
) -> tuple[WechatAccount, WechatSession, list[dict[str, Any]], str]:
    account_result = await db.execute(
        select(WechatAccount)
        .where(
            WechatAccount.user_id == user.id,
            WechatAccount.is_active.is_(True),
            WechatAccount.token_status == TokenStatus.VALID,
        )
        .order_by(WechatAccount.updated_at.desc())
        .limit(1)
    )
    account = account_result.scalar_one_or_none()
    if account is None:
        raise SourceServiceError("请先完成有效的微信公众号扫码授权。")

    session_result = await db.execute(
        select(WechatSession)
        .where(
            WechatSession.wechat_account_id == account.id,
            WechatSession.status == TokenStatus.VALID,
        )
        .order_by(WechatSession.created_at.desc())
        .limit(1)
    )
    session = session_result.scalar_one_or_none()
    if session is None or not session.token_encrypted or not session.cookies_encrypted:
        raise SourceServiceError("当前公众号授权缺少 token 或 cookie，请重新扫码授权。")

    if session.expires_at is not None and session.expires_at <= datetime.now(UTC):
        account.token_status = TokenStatus.EXPIRED
        session.status = TokenStatus.EXPIRED
        await db.commit()
        raise SourceServiceError("当前公众号授权已过期，请重新扫码授权。")

    try:
        cookies = json.loads(session.cookies_encrypted)
    except json.JSONDecodeError as exc:
        account.token_status = TokenStatus.INVALID
        session.status = TokenStatus.INVALID
        await db.commit()
        raise SourceServiceError("当前公众号授权数据异常，请重新扫码授权。") from exc

    if not isinstance(cookies, list):
        raise SourceServiceError("当前公众号授权 cookie 格式异常，请重新扫码授权。")

    return account, session, cookies, session.token_encrypted


async def list_user_sources(db: AsyncSession, user: User) -> list[dict[str, Any]]:
    rows = await db.execute(
        select(
            WechatSource,
            func.count(Article.id).label("article_count"),
            func.max(Article.publish_time).label("last_article_at"),
        )
        .outerjoin(
            Article,
            (Article.source_id == WechatSource.id) & (Article.deleted_at.is_(None)),
        )
        .where(WechatSource.user_id == user.id, WechatSource.deleted_at.is_(None))
        .group_by(WechatSource.id)
        .order_by(WechatSource.updated_at.desc())
    )

    return [
        _serialize_source(
            source,
            article_count=article_count,
            last_article_at=last_article_at,
        )
        for source, article_count, last_article_at in rows.all()
    ]


async def search_wechat_sources(
    db: AsyncSession,
    user: User,
    keyword: str,
    begin: int = 0,
    count: int = 5,
) -> list[dict[str, Any]]:
    _, session, cookies, token = await get_active_authorized_session(db, user)
    headers = {**MP_HEADERS, "Cookie": wechat_login_manager._cookie_header(cookies)}

    async with httpx.AsyncClient(
        headers=headers,
        timeout=httpx.Timeout(20.0, connect=10.0),
        follow_redirects=True,
    ) as client:
        response = await client.get(
            f"{MP_BASE_URL}/cgi-bin/searchbiz",
            params={
                "action": "search_biz",
                "token": token,
                "lang": "zh_CN",
                "f": "json",
                "ajax": "1",
                "random": datetime.now(UTC).timestamp(),
                "query": keyword,
                "begin": begin,
                "count": count,
            },
        )
        response.raise_for_status()
        data = response.json()

    base_resp = data.get("base_resp") or {}
    if base_resp.get("ret") not in (0, "0", None):
        raise SourceServiceError(base_resp.get("err_msg") or "搜索公众号失败，请刷新授权后重试。")

    items = [_normalize_search_item(item) for item in data.get("list", [])]
    fakeids = [item["fakeid"] for item in items if item.get("fakeid")]
    existing: set[str] = set()
    if fakeids:
        existing_result = await db.execute(
            select(WechatSource.fakeid).where(
                WechatSource.user_id == user.id,
                WechatSource.fakeid.in_(fakeids),
                WechatSource.deleted_at.is_(None),
            )
        )
        existing = {value for value in existing_result.scalars().all() if value}

    for item in items:
        item["already_added"] = bool(item.get("fakeid") and item["fakeid"] in existing)
        item["wechat_account_id"] = str(session.wechat_account_id)

    return items


async def add_source_from_search(
    db: AsyncSession,
    user: User,
    payload: dict[str, Any],
) -> dict[str, Any]:
    account, _, _, _ = await get_active_authorized_session(db, user)
    fakeid = payload.get("fakeid")
    if not fakeid:
        raise SourceServiceError("搜索结果缺少 fakeid，不能添加为公众号源。")

    result = await db.execute(
        select(WechatSource).where(
            WechatSource.user_id == user.id,
            WechatSource.fakeid == fakeid,
        )
    )
    source = result.scalar_one_or_none()
    if source is None:
        source = WechatSource(
            user_id=user.id,
            wechat_account_id=account.id,
            name=payload.get("name") or "未命名公众号",
            alias=payload.get("alias"),
            fakeid=fakeid,
            biz=payload.get("biz"),
            avatar_url=payload.get("avatar_url"),
            description=payload.get("description"),
            source_from=SourceFrom.SEARCH,
            status=SourceStatus.ACTIVE,
            raw_data=payload.get("raw_data") or payload,
        )
        db.add(source)
        await db.flush()
    else:
        source.wechat_account_id = account.id
        source.name = payload.get("name") or source.name
        source.alias = payload.get("alias") or source.alias
        source.biz = payload.get("biz") or source.biz
        source.avatar_url = payload.get("avatar_url") or source.avatar_url
        source.description = payload.get("description") or source.description
        source.status = SourceStatus.ACTIVE
        source.deleted_at = None
        source.raw_data = payload.get("raw_data") or payload

    await cache_source_avatar(source)
    await db.commit()
    await db.refresh(source)
    return _serialize_source(source)


async def add_source_from_article_url(
    db: AsyncSession,
    user: User,
    article_url: str,
) -> dict[str, Any]:
    account, _, _, _ = await get_active_authorized_session(db, user)
    parsed = urlparse(article_url)
    if parsed.netloc not in {"mp.weixin.qq.com", "mp.weixin.qq.com.cn"}:
        raise SourceServiceError("请粘贴 mp.weixin.qq.com 的公众号文章链接。")

    query = parse_qs(parsed.query)
    biz = (query.get("__biz") or query.get("biz") or [None])[0]
    if not biz:
        try:
            async with httpx.AsyncClient(
                headers=MP_HEADERS,
                timeout=httpx.Timeout(20.0, connect=10.0),
                follow_redirects=False,
            ) as client:
                response = await client.get(article_url)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SourceServiceError("读取文章链接失败，请检查链接是否可访问。") from exc

        resolved_name = _extract_account_name(response.text)
        if not resolved_name:
            raise SourceServiceError("文章链接中没有解析到公众号名称，请改用公众号搜索添加。")

        candidates = await search_wechat_sources(db, user, resolved_name, count=20)
        matched = next((item for item in candidates if item["name"] == resolved_name), None)
        if matched is None:
            raise SourceServiceError("已解析公众号名称，但没有在微信搜索结果中找到匹配公众号。")

        matched["raw_data"] = {
            **(matched.get("raw_data") or {}),
            "article_url": article_url,
            "resolved_name": resolved_name,
        }
        return await add_source_from_search(db, user, matched)

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
            wechat_account_id=account.id,
            name="待识别公众号",
            biz=biz,
            source_from=SourceFrom.ARTICLE_URL,
            status=SourceStatus.ACTIVE,
            raw_data={"article_url": article_url},
        )
        db.add(source)
        await db.flush()
    else:
        source.wechat_account_id = account.id
        source.status = SourceStatus.ACTIVE
        source.deleted_at = None
        source.raw_data = {**(source.raw_data or {}), "article_url": article_url}

    await cache_source_avatar(source)
    await db.commit()
    await db.refresh(source)
    return _serialize_source(source)


async def get_user_source(db: AsyncSession, user: User, source_id: str) -> WechatSource:
    result = await db.execute(
        select(WechatSource).where(
            WechatSource.id == source_id,
            WechatSource.user_id == user.id,
            WechatSource.deleted_at.is_(None),
        )
    )
    source = result.scalar_one_or_none()
    if source is None:
        raise SourceServiceError("公众号源不存在。")
    return source


async def refresh_source_info(
    db: AsyncSession,
    user: User,
    source_id: str,
) -> dict[str, Any]:
    source = await get_user_source(db, user, source_id)
    candidates = await search_wechat_sources(db, user, source.name, count=20)
    matched = None
    if source.fakeid:
        matched = next((item for item in candidates if item.get("fakeid") == source.fakeid), None)
    if matched is None:
        matched = next((item for item in candidates if item["name"] == source.name), None)
    if matched is None:
        raise SourceServiceError("没有在微信搜索结果中找到这个公众号。")

    source.name = matched.get("name") or source.name
    source.alias = matched.get("alias") or source.alias
    source.fakeid = matched.get("fakeid") or source.fakeid
    source.biz = matched.get("biz") or source.biz
    source.avatar_url = matched.get("avatar_url") or source.avatar_url
    source.description = matched.get("description") or source.description
    source.raw_data = {
        **(source.raw_data or {}),
        "refreshed_at": datetime.now(UTC).isoformat(),
        "refresh_result": matched.get("raw_data") or matched,
    }

    await cache_source_avatar(source)
    await db.commit()
    await db.refresh(source)
    return _serialize_source(source)


async def update_source_status(
    db: AsyncSession,
    user: User,
    source_id: str,
    source_status: SourceStatus,
) -> dict[str, Any]:
    source = await get_user_source(db, user, source_id)
    source.status = source_status
    if source_status != SourceStatus.ACTIVE:
        source.auto_fetch_enabled = False
    await db.commit()
    await db.refresh(source)
    return _serialize_source(source)


async def update_source_auto_fetch(
    db: AsyncSession,
    user: User,
    source_id: str,
    enabled: bool,
) -> dict[str, Any]:
    source = await get_user_source(db, user, source_id)
    if enabled and source.status != SourceStatus.ACTIVE:
        raise SourceServiceError("只有状态正常的公众号源可以开启自动抓取。")
    if enabled:
        await get_active_authorized_session(db, user)
    source.auto_fetch_enabled = enabled
    await db.commit()
    await db.refresh(source)
    return _serialize_source(source)


async def delete_source_tree(db: AsyncSession, user: User, source_id: str) -> None:
    source = await get_user_source(db, user, source_id)
    now = datetime.now(UTC)
    source.deleted_at = now
    source.status = SourceStatus.PAUSED
    source.auto_fetch_enabled = False
    article_result = await db.execute(
        select(Article).where(Article.source_id == source.id, Article.deleted_at.is_(None))
    )
    for article in article_result.scalars().all():
        article.deleted_at = now
    await db.commit()


def to_http_error(exc: SourceServiceError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
