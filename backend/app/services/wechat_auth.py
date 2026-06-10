from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import TokenStatus, WechatLoginStatus
from app.models.user import User
from app.models.wechat import WechatAccount, WechatLoginSession, WechatSession
from app.schemas.wechat import WechatAccountResponse, WechatLoginSessionResponse
from app.services.wechat_login_driver import WechatLoginDriverError, wechat_login_manager


def serialize_wechat_account(
    account: WechatAccount,
    session: WechatSession | None = None,
) -> WechatAccountResponse:
    return WechatAccountResponse(
        id=str(account.id),
        nickname=account.nickname,
        avatar_url=account.avatar_url,
        username=account.username,
        biz=account.biz,
        token_status=account.token_status.value,
        is_active=account.is_active,
        last_verified_at=account.last_verified_at,
        expires_at=session.expires_at if session else None,
    )


def serialize_login_session(session: WechatLoginSession) -> WechatLoginSessionResponse:
    message = session.error_message
    if session.qr_url is None and session.status == WechatLoginStatus.WAITING_SCAN:
        message = "正在生成微信扫码二维码"
    elif session.status == WechatLoginStatus.SCANNED:
        message = "已扫码，请在手机上确认登录"
    elif session.status == WechatLoginStatus.CONFIRMED:
        message = "授权成功"

    return WechatLoginSessionResponse(
        login_id=session.login_id,
        status=session.status.value,
        qr_url=session.qr_url,
        expires_at=session.expires_at,
        message=message,
    )


async def get_active_wechat_account(
    db: AsyncSession,
    user: User,
) -> WechatAccountResponse | None:
    result = await db.execute(
        select(WechatAccount)
        .where(WechatAccount.user_id == user.id, WechatAccount.is_active.is_(True))
        .order_by(WechatAccount.updated_at.desc())
        .limit(1)
    )
    account = result.scalar_one_or_none()
    if account is None:
        return None

    session_result = await db.execute(
        select(WechatSession)
        .where(WechatSession.wechat_account_id == account.id)
        .order_by(WechatSession.created_at.desc())
        .limit(1)
    )
    session = session_result.scalar_one_or_none()
    return serialize_wechat_account(account, session)


async def create_login_session(db: AsyncSession, user: User) -> WechatLoginSessionResponse:
    session = WechatLoginSession(
        user_id=user.id,
        login_id=uuid4().hex,
        status=WechatLoginStatus.WAITING_SCAN,
        qr_url=None,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
        raw_data={"provider": "wechat_mp", "driver": "playwright_pending"},
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    try:
        await wechat_login_manager.start(session.login_id, user.id)
    except WechatLoginDriverError:
        await db.refresh(session)
    else:
        await db.refresh(session)

    return serialize_login_session(session)


async def get_login_session(
    db: AsyncSession,
    user: User,
    login_id: str,
) -> WechatLoginSessionResponse | None:
    result = await db.execute(
        select(WechatLoginSession).where(
            WechatLoginSession.user_id == user.id,
            WechatLoginSession.login_id == login_id,
        )
    )
    session = result.scalar_one_or_none()
    if session is None:
        return None

    if session.status == WechatLoginStatus.WAITING_SCAN and session.expires_at <= datetime.now(UTC):
        session.status = WechatLoginStatus.EXPIRED
        await db.commit()
        await db.refresh(session)

    return serialize_login_session(session)


async def deactivate_active_wechat_account(db: AsyncSession, user: User) -> None:
    await db.execute(
        update(WechatAccount)
        .where(WechatAccount.user_id == user.id, WechatAccount.is_active.is_(True))
        .values(is_active=False, token_status=TokenStatus.INVALID)
    )
    await db.commit()
