from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.wechat import WechatAccountResponse, WechatLoginSessionResponse
from app.services.wechat_auth import (
    create_login_session,
    deactivate_active_wechat_account,
    get_active_wechat_account,
    get_login_session,
    refresh_active_wechat_account,
)
from app.services.wechat_login_driver import WechatLoginDriverError

router = APIRouter()


@router.get("/accounts/current", response_model=WechatAccountResponse | None)
async def get_current_wechat_account(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WechatAccountResponse | None:
    return await get_active_wechat_account(db, current_user)


@router.post("/login/qrcode", response_model=WechatLoginSessionResponse)
async def create_wechat_qr_login(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WechatLoginSessionResponse:
    return await create_login_session(db, current_user)


@router.get("/login/{login_id}/status", response_model=WechatLoginSessionResponse)
async def get_wechat_login_status(
    login_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WechatLoginSessionResponse:
    login_session = await get_login_session(db, current_user, login_id)
    if login_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Wechat login session not found",
        )
    return login_session


@router.post("/accounts/logout")
async def logout_wechat_account(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    await deactivate_active_wechat_account(db, current_user)
    return {"ok": True}


@router.post("/accounts/refresh", response_model=WechatAccountResponse)
async def refresh_wechat_account(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WechatAccountResponse:
    try:
        account = await refresh_active_wechat_account(db, current_user)
    except WechatLoginDriverError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Wechat account not found",
        )
    return account
