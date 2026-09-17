from datetime import datetime

from pydantic import BaseModel


class WereadSessionResponse(BaseModel):
    status: str
    nickname: str | None = None
    last_verified_at: datetime | None
    expires_at: datetime | None


class WereadLoginSessionResponse(BaseModel):
    login_id: str
    status: str
    qr_url: str | None
    expires_at: datetime
    message: str | None = None
