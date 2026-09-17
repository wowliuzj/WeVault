from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import TokenStatus, WechatLoginStatus
from app.models.user import User
from app.models.wechat import WereadLoginSession, WereadSession
from app.schemas.weread import WereadLoginSessionResponse, WereadSessionResponse
from app.services.weread_client import WereadClient, get_active_weread_session
from app.services.weread_login_driver import WereadLoginError, weread_login_manager


def serialize_login(session: WereadLoginSession) -> WereadLoginSessionResponse:
    return WereadLoginSessionResponse(
        login_id=session.login_id,
        status=session.status.value,
        qr_url=session.qr_url,
        expires_at=session.expires_at,
        message=session.error_message,
    )


async def current_session(db: AsyncSession, user: User) -> WereadSessionResponse | None:
    result = await db.execute(select(WereadSession).where(WereadSession.user_id == user.id))
    session = result.scalar_one_or_none()
    if session is None:
        return None
    return WereadSessionResponse(
        status=session.status.value,
        nickname=session.nickname,
        last_verified_at=session.last_verified_at,
        expires_at=session.expires_at,
    )


async def create_login(db: AsyncSession, user: User) -> WereadLoginSessionResponse:
    session = WereadLoginSession(
        user_id=user.id,
        login_id=uuid4().hex,
        status=WechatLoginStatus.WAITING_SCAN,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
        raw_data={"provider": "weread"},
    )
    db.add(session)
    await db.commit()
    try:
        await weread_login_manager.start(session.login_id, user.id)
    except WereadLoginError as exc:
        session.status = WechatLoginStatus.FAILED
        session.error_message = str(exc)
        await db.commit()
    await db.refresh(session)
    return serialize_login(session)


async def get_login(
    db: AsyncSession, user: User, login_id: str
) -> WereadLoginSessionResponse | None:
    result = await db.execute(
        select(WereadLoginSession).where(
            WereadLoginSession.user_id == user.id, WereadLoginSession.login_id == login_id
        )
    )
    session = result.scalar_one_or_none()
    return serialize_login(session) if session else None


async def refresh_session(db: AsyncSession, user: User) -> WereadSessionResponse:
    session, credentials = await get_active_weread_session(db, user)
    info = await WereadClient(credentials).verify()
    session.status = TokenStatus.VALID
    session.last_verified_at = datetime.now(UTC)
    session.last_used_at = session.last_verified_at
    session.nickname = info.get("name") or info.get("nickname") or session.nickname
    await db.commit()
    return WereadSessionResponse(
        status=session.status.value,
        nickname=info.get("name") or info.get("nickname"),
        last_verified_at=session.last_verified_at,
        expires_at=session.expires_at,
    )


async def logout(db: AsyncSession, user: User) -> None:
    result = await db.execute(select(WereadSession).where(WereadSession.user_id == user.id))
    session = result.scalar_one_or_none()
    if session:
        session.status = TokenStatus.INVALID
        session.credentials_encrypted = None
        await db.commit()
