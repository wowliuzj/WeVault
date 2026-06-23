from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.models.enums import UserStatus
from app.models.user import User
from app.schemas.auth import TokenResponse, UserCreate, UserLogin, UserResponse, UserUpdate
from app.services.turnstile import verify_turnstile_token

router = APIRouter()


def serialize_user(user: User) -> UserResponse:
    return UserResponse(
        id=str(user.id),
        email=user.email,
        display_name=user.display_name,
        status=user.status.value,
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: UserCreate, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    await verify_turnstile_token(payload.turnstile_token)

    if payload.invite_code.strip().lower() != "cloud":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="邀请码无效",
        )

    result = await db.execute(select(User).where(User.email == payload.email))
    existing_user = result.scalar_one_or_none()
    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name or payload.email.split("@")[0],
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    access_token = create_access_token(str(user.id))
    return TokenResponse(access_token=access_token, user=serialize_user(user))


@router.post("/login", response_model=TokenResponse)
async def login(payload: UserLogin, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    await verify_turnstile_token(payload.turnstile_token)

    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if user.status == UserStatus.DISABLED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled",
        )

    access_token = create_access_token(str(user.id))
    return TokenResponse(access_token=access_token, user=serialize_user(user))


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)) -> UserResponse:
    return serialize_user(current_user)


@router.patch("/me", response_model=UserResponse)
async def update_me(
    payload: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    if "display_name" in payload.model_fields_set:
        display_name = payload.display_name.strip() if payload.display_name else None
        current_user.display_name = display_name or current_user.email.split("@")[0]

    if payload.new_password:
        current_user.password_hash = hash_password(payload.new_password)

    db.add(current_user)
    await db.commit()
    await db.refresh(current_user)
    return serialize_user(current_user)


@router.post("/logout")
async def logout() -> dict[str, bool]:
    return {"ok": True}
