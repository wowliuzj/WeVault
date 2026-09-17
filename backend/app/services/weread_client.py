from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import TokenStatus
from app.models.user import User
from app.models.wechat import WereadSession
from app.services.secret_box import decrypt_text

WEREAD_BASE_URL = "https://weread.qq.com"
WEREAD_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://weread.qq.com/",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 Chrome/125 Safari/537.36"
    ),
}


class WereadError(RuntimeError):
    pass


def credentials_headers(credentials: dict[str, Any]) -> dict[str, str]:
    vid = str(credentials.get("vid") or "")
    skey = str(credentials.get("skey") or "")
    return {
        **WEREAD_HEADERS,
        "x-vid": vid,
        "x-skey": skey,
        "Cookie": f"wr_vid={vid}; wr_skey={skey}",
    }


async def get_active_weread_session(
    db: AsyncSession, user: User
) -> tuple[WereadSession, dict[str, Any]]:
    result = await db.execute(
        select(WereadSession).where(
            WereadSession.user_id == user.id,
            WereadSession.status == TokenStatus.VALID,
        )
    )
    session = result.scalar_one_or_none()
    if session is None or not session.credentials_encrypted:
        raise WereadError("请先完成有效的微信读书扫码授权。")
    if session.expires_at and session.expires_at <= datetime.now(UTC):
        session.status = TokenStatus.EXPIRED
        await db.commit()
        raise WereadError("微信读书授权已过期，请重新扫码授权。")
    try:
        credentials = json.loads(decrypt_text(session.credentials_encrypted))
    except (ValueError, json.JSONDecodeError) as exc:
        session.status = TokenStatus.INVALID
        await db.commit()
        raise WereadError("微信读书授权数据异常，请重新扫码授权。") from exc
    return session, credentials


class WereadClient:
    def __init__(self, credentials: dict[str, Any]) -> None:
        self.credentials = credentials

    async def request(self, path: str, *, params: dict[str, Any] | None = None) -> httpx.Response:
        async with httpx.AsyncClient(
            base_url=WEREAD_BASE_URL,
            headers=credentials_headers(self.credentials),
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=True,
        ) as client:
            response = await client.get(path, params=params)
        if response.status_code in {401, 403, 499}:
            raise WereadError("微信读书授权已失效，请重新扫码授权。")
        response.raise_for_status()
        try:
            data = response.json()
        except ValueError:
            data = None
        if isinstance(data, dict):
            err_code = data.get("errCode")
            if err_code not in (None, 0, "0"):
                err_message = str(data.get("errMsg") or "").strip()
                if err_code == -2012 or "登录" in err_message:
                    raise WereadError("微信读书登录已超时，请重新扫码授权。")
                detail = err_message or str(err_code)
                raise WereadError(f"微信读书接口返回失败：{detail}")
        return response

    async def verify(self) -> dict[str, Any]:
        response = await self.request("/api/userInfo", params={"userVid": self.credentials["vid"]})
        data = response.json()
        if not isinstance(data, dict):
            raise WereadError("微信读书授权验证失败。")
        return data

    async def list_articles(self, book_id: str, offset: int = 0) -> list[dict[str, Any]]:
        data = (
            await self.request("/web/mp/articles", params={"bookId": book_id, "offset": offset})
        ).json()
        articles: list[dict[str, Any]] = []
        for group in data.get("reviews") or []:
            for sub_review in group.get("subReviews") or []:
                review = sub_review.get("review") or {}
                mp_info = review.get("mpInfo") or {}
                if not mp_info:
                    continue
                review_id = review.get("reviewId") or sub_review.get("reviewId")
                articles.append({**mp_info, "reviewId": review_id, "review": review})
        return articles

    async def fetch_content(self, review_id: str) -> str:
        for attempt in range(3):
            response = await self.request("/web/mp/content", params={"reviewId": review_id})
            content = response.text
            if content.strip():
                markers = ("js_content", "window.cgiDataNew", "content_noencode")
                if not any(marker in content for marker in markers):
                    raise WereadError("微信读书返回内容中没有识别到文章正文。")
                return content
            if attempt < 2:
                await asyncio.sleep(0.8 * (attempt + 1))
        raise WereadError("微信读书正文接口连续返回空内容，请稍后重试。")

    async def list_shelf_mps(self) -> list[dict[str, Any]]:
        data = (
            await self.request(
                "/web/shelf/sync",
                params={"userVid": self.credentials["vid"], "synckey": 0},
            )
        ).json()
        matches: list[dict[str, Any]] = []
        for value in data.get("books") or []:
            if not isinstance(value, dict):
                continue
            book_id = value.get("bookId")
            if not isinstance(book_id, str) or not book_id.startswith("MP_WXS_"):
                continue
            book_info = value.get("bookInfo")
            item = {**value, **book_info} if isinstance(book_info, dict) else value
            matches.append({**item, "bookId": book_id})
        return matches

    async def search_mp(self, keyword: str) -> list[dict[str, Any]]:
        data = (await self.request("/api/store/search", params={"keyword": keyword})).json()
        matches: list[dict[str, Any]] = []

        def walk(value: Any) -> None:
            if isinstance(value, dict):
                book_id = value.get("bookId")
                if isinstance(book_id, str) and book_id.startswith("MP_WXS_"):
                    book_info = value.get("bookInfo")
                    item = {**value, **book_info} if isinstance(book_info, dict) else value
                    matches.append({**item, "bookId": book_id})
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(data)
        unique: dict[str, dict[str, Any]] = {}
        for item in matches:
            book_id = item.get("bookId")
            if book_id:
                unique[str(book_id)] = item
        return list(unique.values())
