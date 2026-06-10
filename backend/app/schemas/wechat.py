from datetime import datetime

from pydantic import BaseModel


class WechatAccountResponse(BaseModel):
    id: str
    nickname: str
    avatar_url: str | None
    username: str | None
    biz: str | None
    token_status: str
    is_active: bool
    last_verified_at: datetime | None
    expires_at: datetime | None


class WechatLoginSessionResponse(BaseModel):
    login_id: str
    status: str
    qr_url: str | None
    expires_at: datetime
    message: str | None = None
