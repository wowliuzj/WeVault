from __future__ import annotations

import asyncio
import base64
import io
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
import qrcode
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.enums import TokenStatus, WechatLoginStatus
from app.models.wechat import WereadLoginSession, WereadSession
from app.services.secret_box import encrypt_text
from app.services.weread_client import WEREAD_BASE_URL, WEREAD_HEADERS, WereadClient


@dataclass
class RuntimeLogin:
    uid: str
    task: asyncio.Task[None] | None = None


class WereadLoginError(RuntimeError):
    pass


class WereadLoginManager:
    def __init__(self) -> None:
        self._sessions: dict[str, RuntimeLogin] = {}
        self._lock = asyncio.Lock()

    async def start(self, login_id: str, user_id: UUID) -> None:
        await self.close(login_id)
        async with httpx.AsyncClient(
            base_url=WEREAD_BASE_URL, headers=WEREAD_HEADERS, timeout=20
        ) as client:
            response = await client.get("/api/auth/getLoginUid")
            response.raise_for_status()
            uid = response.json().get("uid")
        if not uid:
            raise WereadLoginError("获取微信读书登录二维码失败。")
        qr_url = self._qr_data_url(f"{WEREAD_BASE_URL}/web/confirm?uid={uid}")
        runtime = RuntimeLogin(uid=uid)
        async with self._lock:
            self._sessions[login_id] = runtime
        await self._update(login_id, qr_url=qr_url, raw_data={"provider": "weread"})
        runtime.task = asyncio.create_task(self._watch(login_id, user_id))

    async def close(self, login_id: str) -> None:
        async with self._lock:
            runtime = self._sessions.pop(login_id, None)
        if (
            runtime
            and runtime.task
            and runtime.task is not asyncio.current_task()
            and not runtime.task.done()
        ):
            runtime.task.cancel()

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
                    async with httpx.AsyncClient(
                        base_url=WEREAD_BASE_URL, headers=WEREAD_HEADERS, timeout=70
                    ) as client:
                        response = await client.get(
                            "/api/auth/getLoginInfo", params={"uid": runtime.uid}
                        )
                        response.raise_for_status()
                        data = response.json()
                except (httpx.HTTPError, ValueError):
                    continue
                if data.get("succeed") and data.get("accessToken") and data.get("webLoginVid"):
                    await self._persist_success(login_id, user_id, data)
                    return
                logic_code = data.get("logicCode")
                if logic_code == "NEED_OTP":
                    await self._update(
                        login_id,
                        status=WechatLoginStatus.SCANNED,
                        error_message="该账号需要双重认证，请先在微信读书网页完成登录。",
                    )
                    return
                if logic_code == "LOGIN_TIMEOUT":
                    break
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

    async def _persist_success(self, login_id: str, user_id: UUID, data: dict[str, Any]) -> None:
        credentials = {"vid": str(data["webLoginVid"]), "skey": str(data["accessToken"])}
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
    def _qr_data_url(value: str) -> str:
        image = qrcode.make(value)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


weread_login_manager = WereadLoginManager()
