from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, TypeVar
from urllib.parse import quote, unquote
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.enums import TokenStatus
from app.models.user import User
from app.models.wechat import WereadSession
from app.services.secret_box import decrypt_text, encrypt_text

WEREAD_BASE_URL = "https://weread.qq.com"
WEREAD_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://weread.qq.com/",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 Chrome/125 Safari/537.36"
    ),
}
_AUTH_ERROR_CODES = {-2012, -2041, "-2012", "-2041"}
T = TypeVar("T")
logger = logging.getLogger(__name__)


class WereadError(RuntimeError):
    pass


class _WereadAuthenticationError(WereadError):
    pass


def _encoded_refresh_token(value: str) -> str:
    return quote(unquote(value), safe="")


def credentials_cookies(credentials: dict[str, Any]) -> dict[str, str]:
    raw_cookies = credentials.get("cookies")
    cookies = {
        str(key): str(value)
        for key, value in (raw_cookies.items() if isinstance(raw_cookies, dict) else [])
        if key and value is not None
    }
    vid = str(credentials.get("vid") or "")
    skey = str(credentials.get("skey") or "")
    refresh_token = str(credentials.get("refresh_token") or "")
    if vid:
        cookies.setdefault("wr_vid", vid)
    if skey:
        cookies.setdefault("wr_skey", skey)
    if refresh_token:
        cookies.setdefault("wr_rt", _encoded_refresh_token(refresh_token))
    return cookies


def credentials_headers(credentials: dict[str, Any]) -> dict[str, str]:
    cookies = credentials_cookies(credentials)
    vid = str(cookies.get("wr_vid") or credentials.get("vid") or "")
    skey = str(cookies.get("wr_skey") or credentials.get("skey") or "")
    cookie_header = "; ".join(f"{key}={value}" for key, value in cookies.items())
    return {
        **WEREAD_HEADERS,
        "x-vid": vid,
        "x-skey": skey,
        "Cookie": cookie_header,
    }


def _stored_credentials(credentials: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in credentials.items() if not key.startswith("_")}


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
    credentials["_session_id"] = str(session.id)
    return session, credentials


class WereadClient:
    _renew_locks: dict[str, asyncio.Lock] = {}

    def __init__(self, credentials: dict[str, Any]) -> None:
        self.credentials = credentials

    async def request(self, path: str, *, params: dict[str, Any] | None = None) -> httpx.Response:
        async def action() -> httpx.Response:
            return await self._request_once(path, params=params)

        try:
            return await action()
        except _WereadAuthenticationError as auth_error:
            return await self._renew_then_retry(action, auth_error=auth_error)

    async def renew_and_verify(self) -> dict[str, Any]:
        async def action() -> dict[str, Any]:
            response = await self._request_once(
                "/api/userInfo", params={"userVid": self.credentials["vid"]}
            )
            data = response.json()
            if not isinstance(data, dict):
                raise WereadError("微信读书授权验证失败。")
            return data

        return await self._renew_then_retry(action, force_renew=True)

    async def _request_once(
        self, path: str, *, params: dict[str, Any] | None = None
    ) -> httpx.Response:
        cookies = credentials_cookies(self.credentials)
        headers = credentials_headers(self.credentials)
        headers.pop("Cookie", None)
        async with httpx.AsyncClient(
            base_url=WEREAD_BASE_URL,
            headers=headers,
            cookies=cookies,
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=True,
        ) as client:
            response = await client.get(path, params=params)
        self._validate_response(response)
        return response

    async def _renew_then_retry(
        self,
        action: Callable[[], Awaitable[T]],
        *,
        auth_error: _WereadAuthenticationError | None = None,
        force_renew: bool = False,
    ) -> T:
        session_id = self.credentials.get("_session_id")
        lock_key = str(session_id or self.credentials.get("vid") or "anonymous")
        lock = self._renew_locks.setdefault(lock_key, asyncio.Lock())
        async with lock:
            if session_id:
                return await self._renew_with_persistence(
                    UUID(str(session_id)),
                    action,
                    auth_error=auth_error,
                    force_renew=force_renew,
                )
            if auth_error is not None and not self._can_renew():
                raise auth_error
            try:
                await self._renew_once()
                return await action()
            except _WereadAuthenticationError as exc:
                raise WereadError("微信读书登录已超时，自动续期失败，请重新扫码授权。") from exc

    async def _renew_with_persistence(
        self,
        session_id: UUID,
        action: Callable[[], Awaitable[T]],
        *,
        auth_error: _WereadAuthenticationError | None,
        force_renew: bool,
    ) -> T:
        async with AsyncSessionLocal() as db, db.begin():
            session = (
                await db.execute(
                    select(WereadSession)
                    .where(WereadSession.id == session_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if session is None or not session.credentials_encrypted:
                raise WereadError("微信读书授权不存在，请重新扫码授权。")

            previous_skey = str(credentials_cookies(self.credentials).get("wr_skey") or "")
            latest = json.loads(decrypt_text(session.credentials_encrypted))
            latest["_session_id"] = str(session_id)
            self.credentials.clear()
            self.credentials.update(latest)
            latest_skey = str(credentials_cookies(self.credentials).get("wr_skey") or "")

            if not force_renew and latest_skey and latest_skey != previous_skey:
                try:
                    result = await action()
                except _WereadAuthenticationError:
                    pass
                else:
                    session.status = TokenStatus.VALID
                    session.last_verified_at = datetime.now(UTC)
                    return result

            try:
                await self._renew_once()
                result = await action()
            except (_WereadAuthenticationError, WereadError) as exc:
                if auth_error is not None or isinstance(exc, _WereadAuthenticationError):
                    session.status = TokenStatus.EXPIRED
                if auth_error is not None and not self._can_renew():
                    raise auth_error from exc
                raise

            now = datetime.now(UTC)
            session.credentials_encrypted = encrypt_text(
                json.dumps(_stored_credentials(self.credentials))
            )
            session.status = TokenStatus.VALID
            session.last_verified_at = now
            session.last_renewed_at = now
            session.last_used_at = now
            return result

    async def _renew_once(self) -> None:
        if not self._can_renew():
            raise WereadError("当前微信读书授权缺少续期凭据，请重新扫码授权一次。")

        cookies = credentials_cookies(self.credentials)
        headers = credentials_headers(self.credentials)
        headers.pop("Cookie", None)
        headers.update(
            {
                "Content-Type": "application/json",
                "Origin": WEREAD_BASE_URL,
            }
        )
        try:
            async with httpx.AsyncClient(
                base_url=WEREAD_BASE_URL,
                headers=headers,
                cookies=cookies,
                timeout=httpx.Timeout(20.0, connect=10.0),
                follow_redirects=True,
            ) as client:
                response = await client.post(
                    "/web/login/renewal",
                    content=json.dumps(
                        {"rq": "%2Fweb%2Fbook%2Fread", "ql": True}, separators=(",", ":")
                    ),
                )
                response.raise_for_status()
                updated_cookies = self._cookie_jar_dict(client.cookies)
                updated_cookies.update(self._cookie_jar_dict(response.cookies))
        except httpx.HTTPError as exc:
            raise WereadError("微信读书自动续期请求失败，请稍后重试。") from exc

        try:
            data = response.json()
        except ValueError:
            data = None
        if isinstance(data, dict):
            err_code = data.get("errCode")
            if err_code not in (None, 0, "0"):
                detail = str(data.get("errMsg") or err_code)
                raise WereadError(f"微信读书自动续期失败：{detail}")
            if not updated_cookies.get("wr_skey"):
                for key in ("wr_skey", "skey", "token"):
                    value = data.get(key)
                    if value:
                        updated_cookies["wr_skey"] = str(value)
                        break

        if not updated_cookies.get("wr_skey"):
            raise WereadError("微信读书自动续期未返回新的授权信息，请重新扫码授权。")

        merged_cookies = {**cookies, **updated_cookies}
        self.credentials["cookies"] = merged_cookies
        self.credentials["vid"] = str(merged_cookies.get("wr_vid") or self.credentials.get("vid"))
        self.credentials["skey"] = str(merged_cookies["wr_skey"])
        if merged_cookies.get("wr_rt"):
            self.credentials["refresh_token"] = unquote(merged_cookies["wr_rt"])

    def _can_renew(self) -> bool:
        cookies = credentials_cookies(self.credentials)
        return bool(cookies.get("wr_rt") or self.credentials.get("refresh_token"))

    @staticmethod
    def _cookie_jar_dict(cookies: httpx.Cookies) -> dict[str, str]:
        result: dict[str, str] = {}
        for cookie in cookies.jar:
            if cookie.value:
                result[cookie.name] = cookie.value
        return result

    @staticmethod
    def _validate_response(response: httpx.Response) -> None:
        if response.status_code in {401, 403, 499}:
            raise _WereadAuthenticationError("微信读书授权已失效，请重新扫码授权。")
        response.raise_for_status()
        try:
            data = response.json()
        except ValueError:
            data = None
        if not isinstance(data, dict):
            return
        err_code = data.get("errCode")
        if err_code in (None, 0, "0"):
            return
        err_message = str(data.get("errMsg") or "").strip()
        if err_code in _AUTH_ERROR_CODES or "登录" in err_message or "鉴权" in err_message:
            raise _WereadAuthenticationError("微信读书登录已超时，请重新扫码授权。")
        detail = err_message or str(err_code)
        raise WereadError(f"微信读书接口返回失败：{detail}")

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
            content_length = len(content)
            logger.info(
                "WeRead content response review_id=%s attempt=%s status=%s content_length=%s content_type=%s",
                review_id,
                attempt + 1,
                response.status_code,
                content_length,
                response.headers.get("content-type", ""),
            )
            if content.strip():
                markers = ("js_content", "window.cgiDataNew", "content_noencode")
                if not any(marker in content for marker in markers):
                    logger.warning(
                        "WeRead content response has no recognized markers review_id=%s content_length=%s",
                        review_id,
                        content_length,
                    )
                    raise WereadError("微信读书返回内容中没有识别到文章正文。")
                return content
            if attempt < 2:
                await asyncio.sleep(0.8 * (attempt + 1))
        logger.warning(
            "WeRead content response remained empty review_id=%s attempts=3",
            review_id,
        )
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
