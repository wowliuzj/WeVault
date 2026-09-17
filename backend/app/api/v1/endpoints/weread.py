from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.weread import WereadLoginSessionResponse, WereadSessionResponse
from app.services.weread_auth import (
    create_login,
    current_session,
    get_login,
    logout,
    refresh_session,
)
from app.services.weread_client import WereadError

router = APIRouter()


@router.get("/session", response_model=WereadSessionResponse | None)
async def get_session(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    return await current_session(db, current_user)


@router.post("/login/qrcode", response_model=WereadLoginSessionResponse)
async def start_login(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    return await create_login(db, current_user)


@router.get("/login/{login_id}/status", response_model=WereadLoginSessionResponse)
async def login_status(
    login_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await get_login(db, current_user, login_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="WeRead login session not found"
        )
    return result


@router.post("/session/refresh", response_model=WereadSessionResponse)
async def refresh(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    try:
        return await refresh_session(db, current_user)
    except WereadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/session/logout")
async def disconnect(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    await logout(db, current_user)
    return {"ok": True}
