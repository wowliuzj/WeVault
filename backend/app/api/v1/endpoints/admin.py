from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.models.admin import Admin
from app.models.article import Article, ArticleContent
from app.models.enums import UserStatus
from app.models.user import User
from app.models.wechat import WechatAccount, WechatSession, WechatSource
from app.schemas.admin import (
    AdminCreate,
    AdminLogin,
    AdminResponse,
    AdminTokenResponse,
    AdminUpdate,
    ConsoleArticleDetailResponse,
    ConsoleArticleListResponse,
    ConsoleArticleResponse,
    ConsoleArticleSourceResponse,
    ConsoleSourceResponse,
    ConsoleUserDetailResponse,
    ConsoleUserResponse,
    ConsoleUserUpdate,
    ConsoleWechatAccountResponse,
)
from app.services.turnstile import verify_turnstile_token

router = APIRouter()


def serialize_admin(admin: Admin) -> AdminResponse:
    return AdminResponse(
        id=str(admin.id),
        email=admin.email,
        display_name=admin.display_name,
        status=admin.status.value,
        created_at=admin.created_at.isoformat(),
        updated_at=admin.updated_at.isoformat(),
    )


def serialize_wechat_account(
    account: WechatAccount,
    session: WechatSession | None = None,
) -> ConsoleWechatAccountResponse:
    return ConsoleWechatAccountResponse(
        id=str(account.id),
        nickname=account.nickname,
        avatar_url=account.avatar_url,
        username=account.username,
        biz=account.biz,
        token_status=account.token_status.value,
        is_active=account.is_active,
        last_verified_at=account.last_verified_at.isoformat() if account.last_verified_at else None,
        expires_at=session.expires_at.isoformat() if session and session.expires_at else None,
    )


def serialize_user(
    user: User,
    account: WechatAccount | None = None,
    session: WechatSession | None = None,
) -> ConsoleUserResponse:
    return ConsoleUserResponse(
        id=str(user.id),
        email=user.email,
        display_name=user.display_name,
        status=user.status.value,
        created_at=user.created_at.isoformat(),
        updated_at=user.updated_at.isoformat(),
        wechat_account=serialize_wechat_account(account, session) if account else None,
    )


def serialize_source(source: WechatSource, article_count: int) -> ConsoleSourceResponse:
    return ConsoleSourceResponse(
        id=str(source.id),
        name=source.name,
        alias=source.alias,
        avatar_url=source.avatar_url,
        description=source.description,
        status=source.status.value,
        auto_fetch_enabled=source.auto_fetch_enabled,
        last_list_fetched_at=source.last_list_fetched_at.isoformat()
        if source.last_list_fetched_at
        else None,
        article_count=article_count,
    )


def source_avatar_asset_url(source: WechatSource) -> str | None:
    if not source.avatar_storage_path:
        return None
    return f"/api/v1/sources/{source.id}/avatar"


def article_cover_asset_url(article: Article) -> str | None:
    if not article.cover_storage_path:
        return None
    return f"/api/v1/articles/{article.id}/cover"


def serialize_article(article: Article, source: WechatSource) -> ConsoleArticleResponse:
    return ConsoleArticleResponse(
        id=str(article.id),
        title=article.title,
        digest=article.digest,
        cover_url=article.cover_url,
        cover_asset_url=article_cover_asset_url(article),
        original_url=article.original_url,
        publish_time=article.publish_time.isoformat() if article.publish_time else None,
        content_status=article.content_status.value,
        source=ConsoleArticleSourceResponse(
            id=str(source.id),
            name=source.name,
            avatar_url=source.avatar_url,
            avatar_asset_url=source_avatar_asset_url(source),
        ),
        created_at=article.created_at.isoformat(),
        updated_at=article.updated_at.isoformat(),
    )


def serialize_article_detail(
    article: Article,
    source: WechatSource,
    content: ArticleContent | None,
) -> ConsoleArticleDetailResponse:
    data = serialize_article(article, source).model_dump()
    return ConsoleArticleDetailResponse(
        **data,
        content_clean_html=content.clean_html if content else None,
        content_plain_text=content.plain_text if content else None,
    )


async def get_user_wechat_context(
    db: AsyncSession,
    users: list[User],
) -> tuple[dict[UUID, WechatAccount], dict[UUID, WechatSession]]:
    user_ids = [user.id for user in users]
    if not user_ids:
        return {}, {}

    account_result = await db.execute(
        select(WechatAccount)
        .where(WechatAccount.user_id.in_(user_ids), WechatAccount.is_active.is_(True))
        .order_by(WechatAccount.updated_at.desc())
    )
    accounts_by_user: dict[UUID, WechatAccount] = {}
    for account in account_result.scalars().all():
        accounts_by_user.setdefault(account.user_id, account)

    account_ids = [account.id for account in accounts_by_user.values()]
    if not account_ids:
        return accounts_by_user, {}

    session_result = await db.execute(
        select(WechatSession)
        .where(WechatSession.wechat_account_id.in_(account_ids))
        .order_by(WechatSession.created_at.desc())
    )
    sessions_by_account: dict[UUID, WechatSession] = {}
    for session in session_result.scalars().all():
        sessions_by_account.setdefault(session.wechat_account_id, session)

    return accounts_by_user, sessions_by_account


async def get_user_wechat_accounts(
    db: AsyncSession,
    user_id: UUID,
) -> tuple[list[WechatAccount], dict[UUID, WechatSession]]:
    account_result = await db.execute(
        select(WechatAccount)
        .where(WechatAccount.user_id == user_id)
        .order_by(WechatAccount.is_active.desc(), WechatAccount.updated_at.desc())
    )
    accounts = list(account_result.scalars().all())
    if not accounts:
        return [], {}

    session_result = await db.execute(
        select(WechatSession)
        .where(WechatSession.wechat_account_id.in_([account.id for account in accounts]))
        .order_by(WechatSession.created_at.desc())
    )
    sessions_by_account: dict[UUID, WechatSession] = {}
    for session in session_result.scalars().all():
        sessions_by_account.setdefault(session.wechat_account_id, session)
    return accounts, sessions_by_account


async def get_user_sources(db: AsyncSession, user_id: UUID) -> list[ConsoleSourceResponse]:
    rows = await db.execute(
        select(WechatSource, func.count(Article.id))
        .outerjoin(
            Article,
            (Article.source_id == WechatSource.id) & (Article.deleted_at.is_(None)),
        )
        .where(WechatSource.user_id == user_id, WechatSource.deleted_at.is_(None))
        .group_by(WechatSource.id)
        .order_by(WechatSource.updated_at.desc())
    )
    return [
        serialize_source(source, int(article_count or 0))
        for source, article_count in rows.all()
    ]


def parse_admin_status(value: str) -> UserStatus:
    try:
        return UserStatus(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="管理员状态无效。",
        ) from exc


@router.post("/auth/login", response_model=AdminTokenResponse)
async def login(payload: AdminLogin, db: AsyncSession = Depends(get_db)) -> AdminTokenResponse:
    await verify_turnstile_token(payload.turnstile_token)

    email = payload.email.strip().lower()
    result = await db.execute(select(Admin).where(Admin.email == email))
    admin = result.scalar_one_or_none()
    if admin is None or not verify_password(payload.password, admin.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if admin.status == UserStatus.DISABLED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin account is disabled",
        )

    access_token = create_access_token(f"admin:{admin.id}")
    return AdminTokenResponse(access_token=access_token, admin=serialize_admin(admin))


@router.get("/auth/me", response_model=AdminResponse)
async def me(current_admin: Admin = Depends(get_current_admin)) -> AdminResponse:
    return serialize_admin(current_admin)


@router.post("/auth/logout")
async def logout() -> dict[str, bool]:
    return {"ok": True}


@router.get("/admins", response_model=list[AdminResponse])
async def list_admins(
    current_admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> list[AdminResponse]:
    _ = current_admin
    result = await db.execute(select(Admin).order_by(Admin.created_at.desc()).limit(200))
    return [serialize_admin(admin) for admin in result.scalars().all()]


@router.post("/admins", response_model=AdminResponse, status_code=status.HTTP_201_CREATED)
async def create_admin(
    payload: AdminCreate,
    current_admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminResponse:
    _ = current_admin
    email = payload.email.strip().lower()
    result = await db.execute(select(Admin).where(Admin.email == email))
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Admin email already registered",
        )

    admin = Admin(
        email=email,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name or email.split("@")[0],
        status=parse_admin_status(payload.status),
    )
    db.add(admin)
    await db.commit()
    await db.refresh(admin)
    return serialize_admin(admin)


@router.get("/users", response_model=list[ConsoleUserResponse])
async def list_users(
    current_admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> list[ConsoleUserResponse]:
    _ = current_admin
    result = await db.execute(select(User).order_by(User.created_at.desc()).limit(500))
    users = list(result.scalars().all())
    accounts_by_user, sessions_by_account = await get_user_wechat_context(db, users)
    return [
        serialize_user(
            user,
            accounts_by_user.get(user.id),
            sessions_by_account.get(accounts_by_user[user.id].id)
            if user.id in accounts_by_user
            else None,
        )
        for user in users
    ]


@router.get("/users/{user_id}", response_model=ConsoleUserDetailResponse)
async def get_user(
    user_id: UUID,
    current_admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> ConsoleUserDetailResponse:
    _ = current_admin
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在。")
    accounts, sessions_by_account = await get_user_wechat_accounts(db, user.id)
    active_account = next(
        (account for account in accounts if account.is_active),
        accounts[0] if accounts else None,
    )
    active_session = sessions_by_account.get(active_account.id) if active_account else None
    detail = serialize_user(user, active_account, active_session).model_dump()
    return ConsoleUserDetailResponse(
        **detail,
        wechat_accounts=[
            serialize_wechat_account(account, sessions_by_account.get(account.id))
            for account in accounts
        ],
        sources=await get_user_sources(db, user.id),
    )


@router.get("/users/{user_id}/articles", response_model=ConsoleArticleListResponse)
async def list_user_articles(
    user_id: UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=5, le=50),
    keyword: str | None = Query(default=None, max_length=120),
    current_admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> ConsoleArticleListResponse:
    _ = current_admin
    user_result = await db.execute(select(User.id).where(User.id == user_id))
    if user_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在。")

    conditions = [
        Article.user_id == user_id,
        Article.deleted_at.is_(None),
        WechatSource.deleted_at.is_(None),
    ]
    if keyword and keyword.strip():
        pattern = f"%{keyword.strip()}%"
        conditions.append(
            or_(
                Article.title.ilike(pattern),
                Article.digest.ilike(pattern),
                WechatSource.name.ilike(pattern),
            )
        )

    total_result = await db.execute(
        select(func.count())
        .select_from(Article)
        .join(WechatSource, Article.source_id == WechatSource.id)
        .where(*conditions)
    )
    total = int(total_result.scalar_one() or 0)

    result = await db.execute(
        select(Article, WechatSource)
        .join(WechatSource, Article.source_id == WechatSource.id)
        .where(*conditions)
        .order_by(Article.publish_time.desc().nullslast(), Article.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return ConsoleArticleListResponse(
        items=[serialize_article(article, source) for article, source in result.all()],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/articles/{article_id}", response_model=ConsoleArticleDetailResponse)
async def get_article_detail(
    article_id: UUID,
    current_admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> ConsoleArticleDetailResponse:
    _ = current_admin
    result = await db.execute(
        select(Article, WechatSource, ArticleContent)
        .join(WechatSource, Article.source_id == WechatSource.id)
        .outerjoin(ArticleContent, ArticleContent.article_id == Article.id)
        .where(
            Article.id == article_id,
            Article.deleted_at.is_(None),
            WechatSource.deleted_at.is_(None),
        )
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文章不存在。")
    article, source, content = row
    return serialize_article_detail(article, source, content)


@router.patch("/users/{user_id}", response_model=ConsoleUserResponse)
async def update_user(
    user_id: UUID,
    payload: ConsoleUserUpdate,
    current_admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> ConsoleUserResponse:
    _ = current_admin
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在。")

    if "display_name" in payload.model_fields_set:
        display_name = payload.display_name.strip() if payload.display_name else None
        user.display_name = display_name or user.email.split("@")[0]

    if payload.status is not None:
        user.status = parse_admin_status(payload.status)

    if payload.new_password:
        user.password_hash = hash_password(payload.new_password)

    db.add(user)
    await db.commit()
    await db.refresh(user)
    accounts_by_user, sessions_by_account = await get_user_wechat_context(db, [user])
    account = accounts_by_user.get(user.id)
    session = sessions_by_account.get(account.id) if account else None
    return serialize_user(user, account, session)


@router.get("/admins/{admin_id}", response_model=AdminResponse)
async def get_admin(
    admin_id: UUID,
    current_admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminResponse:
    _ = current_admin
    result = await db.execute(select(Admin).where(Admin.id == admin_id))
    admin = result.scalar_one_or_none()
    if admin is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="管理员不存在。")
    return serialize_admin(admin)


@router.patch("/admins/{admin_id}", response_model=AdminResponse)
async def update_admin(
    admin_id: UUID,
    payload: AdminUpdate,
    current_admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminResponse:
    result = await db.execute(select(Admin).where(Admin.id == admin_id))
    admin = result.scalar_one_or_none()
    if admin is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="管理员不存在。")

    if "display_name" in payload.model_fields_set:
        display_name = payload.display_name.strip() if payload.display_name else None
        admin.display_name = display_name or admin.email.split("@")[0]

    if payload.status is not None:
        next_status = parse_admin_status(payload.status)
        if admin.id == current_admin.id and next_status == UserStatus.DISABLED:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="不能禁用当前登录的管理员。",
            )
        admin.status = next_status

    if payload.new_password:
        admin.password_hash = hash_password(payload.new_password)

    db.add(admin)
    await db.commit()
    await db.refresh(admin)
    return serialize_admin(admin)
