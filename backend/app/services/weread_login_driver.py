from __future__ import annotations

import asyncio
import base64
import io
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, unquote
from uuid import UUID

import httpx
import qrcode
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.enums import TokenStatus, WechatLoginStatus
from app.models.wechat import WereadLoginSession, WereadSession
from app.services.secret_box import encrypt_text
from app.services.weread_browser_session import weread_browser_session_manager
from app.services.weread_client import WEREAD_BASE_URL, WEREAD_HEADERS, WereadClient


def _login_value(data: dict[str, Any], *keys: str) -> Any:
    inner = data.get("data") if isinstance(data.get("data"), dict) else {}
    nested = inner.get("data") if isinstance(inner.get("data"), dict) else {}
    for payload in (data, inner, nested):
        for key in keys:
            value = payload.get(key)
            if value not in (None, ""):
                return value
    return None


def build_login_credentials(
    data: dict[str, Any], cookies: dict[str, str]
) -> dict[str, Any]:
    vid = _login_value(data, "webLoginVid", "vid", "userVid", "user_vid")
    access_token = _login_value(data, "accessToken", "access_token", "token")
    refresh_token = _login_value(data, "refreshToken", "refresh_token")
    result_cookies = dict(cookies)
    result_cookies.setdefault("wr_vid", str(vid or ""))
    result_cookies.setdefault("wr_skey", str(access_token or ""))
    if refresh_token:
        result_cookies.setdefault(
            "wr_rt", quote(unquote(str(refresh_token)), safe="")
        )
    return {
        "vid": str(vid or ""),
        "skey": str(result_cookies.get("wr_skey") or access_token or ""),
        "refresh_token": str(refresh_token or ""),
        "cookies": result_cookies,
    }


@dataclass
class RuntimeLogin:
    uid: str
    client: httpx.AsyncClient
    task: asyncio.Task[None] | None = None


class WereadLoginError(RuntimeError):
    pass


class WereadLoginManager:
    def __init__(self) -> None:
        self._sessions: dict[str, RuntimeLogin] = {}
        self._lock = asyncio.Lock()

    async def start(self, login_id: str, user_id: UUID) -> None:
        await self.close(login_id)
        client = httpx.AsyncClient(
            base_url=WEREAD_BASE_URL, headers=WEREAD_HEADERS, timeout=70
        )
        try:
            response = await client.get("/api/auth/getLoginUid")
            response.raise_for_status()
            uid = response.json().get("uid")
        except Exception:
            await client.aclose()
            raise
        if not uid:
            await client.aclose()
            raise WereadLoginError("获取微信读书登录二维码失败。")
        qr_url = self._qr_data_url(f"{WEREAD_BASE_URL}/web/confirm?uid={uid}")
        runtime = RuntimeLogin(uid=uid, client=client)
        async with self._lock:
            self._sessions[login_id] = runtime
        await self._update(login_id, qr_url=qr_url, raw_data={"provider": "weread"})
        runtime.task = asyncio.create_task(self._watch(login_id, user_id))

    async def close(self, login_id: str) -> None:
        async with self._lock:
            runtime = self._sessions.pop(login_id, None)
        if runtime is None:
            return
        if (
            runtime.task
            and runtime.task is not asyncio.current_task()
            and not runtime.task.done()
        ):
            runtime.task.cancel()
        await runtime.client.aclose()

    async def close_all(self) -> None:
        for login_id in list(self._sessions):
            await self.close(login_id)

    async def _watch(self, login_id: str, user_id: UUID) -> None:
        try:
            for _ in range(6):
                runtime = self._sessions.get(login_id)
                if runtime is None:
                    return
                try:
                    response = await runtime.client.get(
                        "/api/auth/getLoginInfo", params={"uid": runtime.uid, "otp": ""}
                    )
                    response.raise_for_status()
                    data = response.json()
                except (httpx.HTTPError, ValueError):
                    continue
                succeed = _login_value(data, "succeed")
                access_token = _login_value(data, "accessToken", "access_token", "token")
                vid = _login_value(data, "webLoginVid", "vid", "userVid", "user_vid")
                if succeed and access_token and vid:
                    await self._persist_success(login_id, user_id, data, runtime.client)
                    return
                logic_code = _login_value(data, "logicCode")
                if logic_code == "NEED_OTP":
                    await self._update(
                        login_id,
                        status=WechatLoginStatus.SCANNED,
                        error_message="该账号需要双重认证，请先在微信读书网页完成登录。",
                    )
                    return
                if logic_code == "LOGIN_TIMEOUT":
                    continue
            await self._update(
                login_id,
                status=WechatLoginStatus.EXPIRED,
                error_message="二维码已失效，请重新扫码。",
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._update(login_id, status=WechatLoginStatus.FAILED, error_message=str(exc))
        finally:
            await self.close(login_id)

    async def _persist_success(
        self,
        login_id: str,
        user_id: UUID,
        data: dict[str, Any],
        client: httpx.AsyncClient,
    ) -> None:
        credentials = build_login_credentials(data, self._cookie_jar_dict(client.cookies))
        user_info = await WereadClient(credentials).verify()
        now = datetime.now(UTC)
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(WereadSession).where(WereadSession.user_id == user_id))
            session = result.scalar_one_or_none()
            if session is None:
                session = WereadSession(user_id=user_id)
                db.add(session)
            session.credentials_encrypted = encrypt_text(json.dumps(credentials))
            session.nickname = user_info.get("name") or user_info.get("nickname")
            session.status = TokenStatus.VALID
            session.last_verified_at = now
            session.last_used_at = now
            login = (
                await db.execute(
                    select(WereadLoginSession).where(WereadLoginSession.login_id == login_id)
                )
            ).scalar_one()
            login.status = WechatLoginStatus.CONFIRMED
            login.confirmed_at = now
            login.error_message = None
            login.raw_data = {
                "provider": "weread",
                "nickname": user_info.get("name") or user_info.get("nickname"),
            }
            await db.commit()
        await weread_browser_session_manager.initialize(user_id)

    async def _update(
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
                select(WereadLoginSession).where(WereadLoginSession.login_id == login_id)
            )
            session = result.scalar_one_or_none()
            if session is None:
                return
            if status is not None:
                session.status = status
            if qr_url is not None:
                session.qr_url = qr_url
            session.error_message = error_message
            if raw_data is not None:
                session.raw_data = raw_data
            await db.commit()

    @staticmethod
    def _cookie_jar_dict(cookies: httpx.Cookies) -> dict[str, str]:
        result: dict[str, str] = {}
        for cookie in cookies.jar:
            if cookie.value:
                result[cookie.name] = cookie.value
        return result

    @staticmethod
    def _qr_data_url(value: str) -> str:
        image = qrcode.make(value)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


weread_login_manager = WereadLoginManager()
