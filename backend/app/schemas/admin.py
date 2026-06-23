from pydantic import BaseModel, EmailStr, Field


class AdminLogin(BaseModel):
    email: EmailStr
    password: str
    turnstile_token: str | None = None


class AdminCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=80)
    status: str = "active"


class AdminUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=80)
    status: str | None = None
    new_password: str | None = Field(default=None, min_length=8, max_length=128)


class AdminResponse(BaseModel):
    id: str
    email: EmailStr
    display_name: str | None
    status: str
    created_at: str
    updated_at: str


class AdminTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    admin: AdminResponse


class ConsoleUserUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=80)
    status: str | None = None
    new_password: str | None = Field(default=None, min_length=8, max_length=128)


class ConsoleWechatAccountResponse(BaseModel):
    id: str
    nickname: str
    avatar_url: str | None
    username: str | None
    biz: str | None
    token_status: str
    is_active: bool
    last_verified_at: str | None
    expires_at: str | None


class ConsoleSourceResponse(BaseModel):
    id: str
    name: str
    alias: str | None
    avatar_url: str | None
    description: str | None
    status: str
    auto_fetch_enabled: bool
    last_list_fetched_at: str | None
    article_count: int


class ConsoleArticleSourceResponse(BaseModel):
    id: str
    name: str
    avatar_url: str | None
    avatar_asset_url: str | None


class ConsoleArticleResponse(BaseModel):
    id: str
    title: str
    digest: str | None
    cover_url: str | None
    cover_asset_url: str | None
    original_url: str
    publish_time: str | None
    content_status: str
    source: ConsoleArticleSourceResponse
    created_at: str
    updated_at: str


class ConsoleArticleDetailResponse(ConsoleArticleResponse):
    content_clean_html: str | None = None
    content_plain_text: str | None = None


class ConsoleArticleListResponse(BaseModel):
    items: list[ConsoleArticleResponse]
    total: int
    page: int
    page_size: int


class ConsoleUserResponse(BaseModel):
    id: str
    email: EmailStr
    display_name: str | None
    status: str
    created_at: str
    updated_at: str
    wechat_account: ConsoleWechatAccountResponse | None = None


class ConsoleUserDetailResponse(ConsoleUserResponse):
    wechat_accounts: list[ConsoleWechatAccountResponse]
    sources: list[ConsoleSourceResponse]
