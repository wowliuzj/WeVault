from __future__ import annotations

import asyncio
import base64
import html
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from http.cookies import SimpleCookie
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select, update

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.enums import TokenStatus, WechatLoginStatus
from app.models.wechat import WechatAccount, WechatLoginSession, WechatSession

MP_BASE_URL = "https://mp.weixin.qq.com"
MP_HEADERS = {
    "Referer": "https://mp.weixin.qq.com/",
    "Origin": "https://mp.weixin.qq.com",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Encoding": "identity",
}


@dataclass
class RuntimeLoginSession:
    client: httpx.AsyncClient
    task: asyncio.Task[None] | None = None


class WechatLoginDriverError(RuntimeError):
    pass


class WechatMpLoginManager:
    def __init__(self) -> None:
        self._sessions: dict[str, RuntimeLoginSession] = {}
        self._lock = asyncio.Lock()

    async def start(self, login_id: str, user_id: UUID) -> None:
        await self.close(login_id)

        client = httpx.AsyncClient(
            headers=MP_HEADERS,
            timeout=httpx.Timeout(20.0, connect=10.0),
            follow_redirects=True,
        )
        try:
            await self._start_login_session(client)
            qr_url = await self._get_qrcode_data_url(client)

            runtime = RuntimeLoginSession(client=client)
            async with self._lock:
                self._sessions[login_id] = runtime

            await self._update_login_session(
                login_id,
                status=WechatLoginStatus.WAITING_SCAN,
                qr_url=qr_url,
                raw_data={"provider": "wechat_mp", "driver": "bizlogin_api"},
            )
            runtime.task = asyncio.create_task(self._watch_login(login_id, user_id))
        except Exception as exc:
            await client.aclose()
            message = self._friendly_error(exc)
            await self._mark_failed(login_id, message)
            raise WechatLoginDriverError(message) from exc

    async def close(self, login_id: str) -> None:
        async with self._lock:
            runtime = self._sessions.pop(login_id, None)
        if runtime is None:
            return
        task = runtime.task
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()
        await runtime.client.aclose()

    async def close_all(self) -> None:
        for login_id in list(self._sessions):
            await self.close(login_id)

    async def _start_login_session(self, client: httpx.AsyncClient) -> None:
        payload = {
            "userlang": "zh_CN",
            "redirect_url": "",
            "login_type": "3",
            "sessionid": f"{int(datetime.now(UTC).timestamp() * 1000)}{uuid4().hex[:4]}",
            "token": "",
            "lang": "zh_CN",
            "f": "json",
            "ajax": "1",
        }
        response = await client.post(
            f"{MP_BASE_URL}/cgi-bin/bizlogin",
            params={"action": "startlogin"},
            data=payload,
        )
        response.raise_for_status()
        data = response.json()
        if data.get("base_resp", {}).get("ret") != 0:
            message = data.get("base_resp", {}).get("err_msg") or "获取登录会话失败"
            raise WechatLoginDriverError(message)
        if not client.cookies.get("uuid"):
            raise WechatLoginDriverError("微信登录会话没有返回 uuid cookie。")

    async def _get_qrcode_data_url(self, client: httpx.AsyncClient) -> str:
        response = await client.get(
            f"{MP_BASE_URL}/cgi-bin/scanloginqrcode",
            params={"action": "getqrcode", "random": int(datetime.now(UTC).timestamp() * 1000)},
        )
        response.raise_for_status()
        if len(response.content) < 500:
            raise WechatLoginDriverError("微信返回的二维码图片为空。")
        encoded = base64.b64encode(response.content).decode("ascii")
        content_type = response.headers.get("content-type", "image/png").split(";")[0]
        return f"data:{content_type};base64,{encoded}"

    async def _watch_login(self, login_id: str, user_id: UUID) -> None:
        runtime = self._sessions.get(login_id)
        if runtime is None:
            return

        deadline = datetime.now(UTC) + timedelta(seconds=settings.wechat_login_timeout_seconds)
        try:
            while datetime.now(UTC) < deadline:
                scan_status = await self._ask_scan_status(runtime.client)
                status = scan_status.get("status")

                if status == 1:
                    await self._login_and_persist(login_id, user_id, runtime.client)
                    return
                if status in {4, 6}:
                    await self._update_login_session(
                        login_id,
                        status=WechatLoginStatus.SCANNED,
                        raw_data={"scan_status": scan_status},
                    )
                elif status in {2, 3}:
                    await self._update_login_session(
                        login_id,
                        status=WechatLoginStatus.EXPIRED,
                        error_message="二维码已失效，请重新扫码登录。",
                        raw_data={"scan_status": scan_status},
                    )
                    return
                elif status == 5:
                    await self._update_login_session(
                        login_id,
                        status=WechatLoginStatus.FAILED,
                        error_message="该微信账号尚未绑定邮箱，不能扫码登录。",
                        raw_data={"scan_status": scan_status},
                    )
                    return

                await asyncio.sleep(2)

            await self._update_login_session(
                login_id,
                status=WechatLoginStatus.EXPIRED,
                error_message="二维码已过期，请重新发起扫码授权。",
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._mark_failed(login_id, self._friendly_error(exc))
        finally:
            await self.close(login_id)

    async def _ask_scan_status(self, client: httpx.AsyncClient) -> dict[str, Any]:
        response = await client.get(
            f"{MP_BASE_URL}/cgi-bin/scanloginqrcode",
            params={
                "action": "ask",
                "token": "",
                "lang": "zh_CN",
                "f": "json",
                "ajax": "1",
            },
        )
        response.raise_for_status()
        return response.json()

    async def _login_and_persist(
        self,
        login_id: str,
        user_id: UUID,
        client: httpx.AsyncClient,
    ) -> None:
        payload = {
            "userlang": "zh_CN",
            "redirect_url": "",
            "cookie_forbidden": "0",
            "cookie_cleaned": "0",
            "plugin_used": "0",
            "login_type": "3",
            "token": "",
            "lang": "zh_CN",
            "f": "json",
            "ajax": "1",
        }
        response = await client.post(
            f"{MP_BASE_URL}/cgi-bin/bizlogin",
            params={"action": "login"},
            data=payload,
        )
        response.raise_for_status()
        data = response.json()
        redirect_url = data.get("redirect_url")
        if not redirect_url:
            raise WechatLoginDriverError(f"登录响应中未找到 redirect_url: {data}")

        token = self._extract_token(redirect_url)
        if not token:
            raise WechatLoginDriverError(f"redirect_url 中未找到 token 参数: {redirect_url}")

        await self._persist_confirmed_login(
            login_id=login_id,
            user_id=user_id,
            token=token,
            cookies=self._parse_set_cookies(response.headers.get_list("set-cookie")),
            redirect_url=redirect_url,
            account_info=await self._fetch_account_info(client, token),
        )

    async def _fetch_account_info(
        self,
        client: httpx.AsyncClient,
        token: str,
    ) -> dict[str, str]:
        try:
            response = await client.get(
                f"{MP_BASE_URL}/cgi-bin/home",
                params={"t": "home/index", "token": token, "lang": "zh_CN"},
            )
            response.raise_for_status()
            page_html = response.text
            return {
                "nickname": self._extract_js_string(page_html, "nick_name") or "已授权公众号",
                "avatar_url": self._extract_js_string(page_html, "head_img") or "",
            }
        except httpx.HTTPError:
            return {"nickname": "已授权公众号", "avatar_url": ""}

    async def _persist_confirmed_login(
        self,
        *,
        login_id: str,
        user_id: UUID,
        token: str,
        cookies: list[dict[str, Any]],
        redirect_url: str,
        account_info: dict[str, str],
    ) -> None:
        now = datetime.now(UTC)
        expires_at = self._cookies_expires_at(cookies) or now + timedelta(days=4)
        account_biz = f"mp-login:{user_id}"

        async with AsyncSessionLocal() as db:
            await db.execute(
                update(WechatAccount)
                .where(WechatAccount.user_id == user_id, WechatAccount.is_active.is_(True))
                .values(is_active=False)
            )

            result = await db.execute(
                select(WechatAccount).where(
                    WechatAccount.user_id == user_id,
                    WechatAccount.biz == account_biz,
                )
            )
            account = result.scalar_one_or_none()
            if account is None:
                account = WechatAccount(
                    user_id=user_id,
                    nickname=account_info["nickname"],
                    avatar_url=account_info["avatar_url"] or None,
                    username=None,
                    biz=account_biz,
                    token_status=TokenStatus.VALID,
                    is_active=True,
                    last_verified_at=now,
                )
                db.add(account)
                await db.flush()
            else:
                account.nickname = account_info["nickname"]
                account.avatar_url = account_info["avatar_url"] or account.avatar_url
                account.token_status = TokenStatus.VALID
                account.is_active = True
                account.last_verified_at = now

            db.add(
                WechatSession(
                    user_id=user_id,
                    wechat_account_id=account.id,
                    token_encrypted=token,
                    cookies_encrypted=json.dumps(cookies, ensure_ascii=False),
                    raw_session_encrypted=json.dumps(
                        {"redirect_url": redirect_url, "cookies": cookies},
                        ensure_ascii=False,
                    ),
                    expires_at=expires_at,
                    last_used_at=now,
                    status=TokenStatus.VALID,
                )
            )

            result = await db.execute(
                select(WechatLoginSession).where(WechatLoginSession.login_id == login_id)
            )
            login_session = result.scalar_one_or_none()
            if login_session is not None:
                login_session.status = WechatLoginStatus.CONFIRMED
                login_session.confirmed_at = now
                login_session.error_message = None
                login_session.raw_data = {
                    "provider": "wechat_mp",
                    "driver": "bizlogin_api",
                    "redirect_url": redirect_url,
                    "token_detected": True,
                }

            await db.commit()

    async def _update_login_session(
        self,
        login_id: str,
        *,
        status: WechatLoginStatus | None = None,
        qr_url: str | None = None,
        error_message: str | None = None,
        raw_data: dict[str, Any] | None = None,
    ) -> None:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(WechatLoginSession).where(WechatLoginSession.login_id == login_id)
            )
            session = result.scalar_one_or_none()
            if session is None:
                return
            if status is not None:
                session.status = status
            if qr_url is not None:
                session.qr_url = qr_url
            if error_message is not None:
                session.error_message = error_message
            if raw_data is not None:
                session.raw_data = {**(session.raw_data or {}), **raw_data}
            await db.commit()

    async def _mark_failed(self, login_id: str, message: str) -> None:
        await self._update_login_session(
            login_id,
            status=WechatLoginStatus.FAILED,
            error_message=message,
        )

    def _extract_token(self, redirect_url: str) -> str | None:
        values = parse_qs(urlparse(redirect_url).query).get("token")
        if not values:
            return None
        return values[0]

    def _extract_js_string(self, page_html: str, key: str) -> str | None:
        match = re.search(rf'wx\.cgiData\.{key}\s*?=\s*?"(?P<value>[^"]*)"', page_html)
        if not match:
            return None
        return html.unescape(match.group("value"))

    def _parse_set_cookies(self, set_cookies: list[str]) -> list[dict[str, Any]]:
        cookies: list[dict[str, Any]] = []
        for value in set_cookies:
            parsed = SimpleCookie()
            parsed.load(value)
            for name, morsel in parsed.items():
                cookie: dict[str, Any] = {"name": name, "value": morsel.value}
                expires = morsel["expires"]
                if expires:
                    try:
                        cookie["expires"] = parsedate_to_datetime(expires).timestamp()
                    except (TypeError, ValueError):
                        pass
                cookies.append(cookie)
        return cookies

    def _cookies_expires_at(self, cookies: list[dict[str, Any]]) -> datetime | None:
        now = datetime.now(UTC)
        expires = [
            datetime.fromtimestamp(cookie["expires"], tz=UTC)
            for cookie in cookies
            if cookie.get("expires", -1) and cookie.get("expires", -1) > 0
        ]
        future_expires = [item for item in expires if item > now]
        if not future_expires:
            return None
        return min(future_expires)

    def _friendly_error(self, exc: Exception) -> str:
        message = str(exc)
        if isinstance(exc, httpx.HTTPError):
            return "连接微信公众平台失败，请检查网络或代理后重试。"
        return message or "扫码授权失败，请稍后重试。"


wechat_login_manager = WechatMpLoginManager()
