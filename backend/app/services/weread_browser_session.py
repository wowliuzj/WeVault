from __future__ import annotations

import asyncio
import json
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote
from uuid import UUID

import httpx
from playwright.async_api import BrowserContext, async_playwright
from sqlalchemy import select

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.article import Article
from app.models.enums import TokenStatus
from app.models.wechat import WereadSession
from app.services.secret_box import decrypt_text, encrypt_text
from app.services.weread_client import (
    WEREAD_BASE_URL,
    WereadError,
    _stored_credentials,
    credentials_cookies,
    credentials_headers,
)

logger = logging.getLogger(__name__)
_CONTENT_MARKERS = ("js_content", "window.cgiDataNew", "content_noencode")


def profile_path(user_id: UUID) -> Path:
    return Path(settings.weread_profile_dir) / str(user_id)


def merge_browser_cookies(
    credentials: dict[str, Any], browser_cookies: list[dict[str, Any]]
) -> dict[str, Any]:
    merged = credentials_cookies(credentials)
    for cookie in browser_cookies:
        name = cookie.get("name")
        value = cookie.get("value")
        if name and value is not None:
            merged[str(name)] = str(value)
    result = dict(credentials)
    result["cookies"] = merged
    result["vid"] = str(merged.get("wr_vid") or result.get("vid") or "")
    result["skey"] = str(merged.get("wr_skey") or result.get("skey") or "")
    if merged.get("wr_rt"):
        result["refresh_token"] = unquote(merged["wr_rt"])
    return result


class WereadBrowserSessionManager:
    def __init__(self) -> None:
        self._locks: dict[UUID, asyncio.Lock] = {}
        self._keepalive_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._keepalive_task is None or self._keepalive_task.done():
            self._keepalive_task = asyncio.create_task(self._keepalive_loop())

    async def close(self) -> None:
        task = self._keepalive_task
        self._keepalive_task = None
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def initialize(self, user_id: UUID) -> None:
        try:
            await self.refresh_user(user_id, mark_expired=False)
        except Exception as exc:
            logger.warning(
                "WeRead browser profile initialization failed user=%s error=%s",
                user_id,
                exc,
            )

    async def refresh_user(
        self,
        user_id: UUID,
        *,
        review_id: str | None = None,
        mark_expired: bool = True,
    ) -> dict[str, Any]:
        lock = self._locks.setdefault(user_id, asyncio.Lock())
        async with lock:
            session_id, credentials = await self._load_credentials(user_id)
            if review_id is None:
                review_id = await self._find_review_id(user_id)
            updated = await self._run_browser(user_id, credentials, review_id)
            try:
                info = await self._verify(updated, review_id)
            except WereadError:
                if mark_expired:
                    await self._mark_expired(session_id)
                raise
            await self._save_credentials(session_id, updated, info)
            return info

    async def clear_profile(self, user_id: UUID) -> None:
        lock = self._locks.setdefault(user_id, asyncio.Lock())
        async with lock:
            path = profile_path(user_id)
            if path.exists():
                await asyncio.to_thread(shutil.rmtree, path)

    async def _load_credentials(self, user_id: UUID) -> tuple[UUID, dict[str, Any]]:
        async with AsyncSessionLocal() as db:
            session = (
                await db.execute(select(WereadSession).where(WereadSession.user_id == user_id))
            ).scalar_one_or_none()
            if session is None or not session.credentials_encrypted:
                raise WereadError("请先完成有效的微信读书扫码授权。")
            credentials = json.loads(decrypt_text(session.credentials_encrypted))
            return session.id, credentials

    async def _find_review_id(self, user_id: UUID) -> str | None:
        async with AsyncSessionLocal() as db:
            return (
                await db.execute(
                    select(Article.weread_review_id)
                    .where(
                        Article.user_id == user_id,
                        Article.weread_review_id.is_not(None),
                        Article.deleted_at.is_(None),
                    )
                    .order_by(Article.publish_time.desc().nullslast(), Article.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()

    async def _run_browser(
        self, user_id: UUID, credentials: dict[str, Any], review_id: str | None
    ) -> dict[str, Any]:
        path = profile_path(user_id)
        path.mkdir(parents=True, exist_ok=True)
        async with async_playwright() as playwright:
            context = await playwright.chromium.launch_persistent_context(
                str(path),
                headless=settings.wechat_browser_headless,
                args=["--disable-dev-shm-usage", "--no-sandbox"],
            )
            try:
                await self._inject_cookies(context, credentials)
                page = context.pages[0] if context.pages else await context.new_page()
                await page.goto(WEREAD_BASE_URL, wait_until="domcontentloaded", timeout=30_000)
                if review_id:
                    await page.goto(
                        f"{WEREAD_BASE_URL}/web/mp/content?reviewId={review_id}",
                        wait_until="domcontentloaded",
                        timeout=30_000,
                    )
                await page.wait_for_timeout(settings.weread_browser_settle_milliseconds)
                browser_cookies = await context.cookies(WEREAD_BASE_URL)
            finally:
                await context.close()
        return merge_browser_cookies(credentials, browser_cookies)

    @staticmethod
    async def _inject_cookies(
        context: BrowserContext, credentials: dict[str, Any]
    ) -> None:
        cookies = [
            {
                "name": name,
                "value": value,
                "domain": ".weread.qq.com",
                "path": "/",
                "secure": True,
                "httpOnly": False,
                "sameSite": "Lax",
            }
            for name, value in credentials_cookies(credentials).items()
            if value
        ]
        if cookies:
            await context.add_cookies(cookies)

    async def _verify(
        self, credentials: dict[str, Any], review_id: str | None
    ) -> dict[str, Any]:
        headers = credentials_headers(credentials)
        headers.pop("Cookie", None)
        async with httpx.AsyncClient(
            base_url=WEREAD_BASE_URL,
            headers=headers,
            cookies=credentials_cookies(credentials),
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=True,
        ) as client:
            if review_id:
                response = await client.get("/web/mp/content", params={"reviewId": review_id})
                if response.status_code not in {200} or not response.text.strip():
                    raise WereadError("微信读书授权未能恢复公众号文章访问，请重新扫码授权。")
                if not any(marker in response.text for marker in _CONTENT_MARKERS):
                    raise WereadError("微信读书授权未能恢复公众号文章访问，请重新扫码授权。")
            else:
                response = await client.get(
                    "/web/shelf/sync",
                    params={"userVid": credentials.get("vid", ""), "synckey": 0},
                )
                try:
                    data = response.json()
                except ValueError as exc:
                    raise WereadError(
                        "微信读书授权验证失败，且当前没有可用于验证的公众号文章，请重新扫码授权。"
                    ) from exc
                if response.status_code != 200 or not isinstance(data, dict) or data.get("errCode"):
                    raise WereadError(
                        "微信读书授权验证失败，且当前没有可用于验证的公众号文章，请重新扫码授权。"
                    )

            user_response = await client.get(
                "/api/userInfo", params={"userVid": credentials.get("vid", "")}
            )
            try:
                info = user_response.json()
            except ValueError:
                info = {}
            return info if isinstance(info, dict) else {}

    async def _save_credentials(
        self, session_id: UUID, credentials: dict[str, Any], info: dict[str, Any]
    ) -> None:
        now = datetime.now(UTC)
        async with AsyncSessionLocal() as db, db.begin():
            session = (
                await db.execute(
                    select(WereadSession).where(WereadSession.id == session_id).with_for_update()
                )
            ).scalar_one_or_none()
            if session is None or not session.credentials_encrypted:
                return
            session.credentials_encrypted = encrypt_text(
                json.dumps(_stored_credentials(credentials))
            )
            session.status = TokenStatus.VALID
            session.last_verified_at = now
            session.last_renewed_at = now
            session.last_used_at = now
            session.nickname = info.get("name") or info.get("nickname") or session.nickname

    async def _mark_expired(self, session_id: UUID) -> None:
        async with AsyncSessionLocal() as db, db.begin():
            session = await db.get(WereadSession, session_id)
            if session:
                session.status = TokenStatus.EXPIRED

    async def _keepalive_loop(self) -> None:
        await asyncio.sleep(settings.weread_keepalive_initial_delay_seconds)
        while True:
            try:
                async with AsyncSessionLocal() as db:
                    user_ids = list(
                        (
                            await db.execute(
                                select(WereadSession.user_id).where(
                                    WereadSession.status == TokenStatus.VALID,
                                    WereadSession.credentials_encrypted.is_not(None),
                                )
                            )
                        ).scalars()
                    )
                for user_id in user_ids:
                    try:
                        await self.refresh_user(user_id, mark_expired=False)
                    except Exception as exc:
                        logger.warning(
                            "WeRead browser keepalive failed user=%s error=%s", user_id, exc
                        )
                    await asyncio.sleep(settings.weread_keepalive_stagger_seconds)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("WeRead browser keepalive loop failed: %s", exc)
            await asyncio.sleep(settings.weread_keepalive_interval_seconds)


weread_browser_session_manager = WereadBrowserSessionManager()
