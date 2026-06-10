from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class WechatAccountResponse(BaseModel):
    id: str
    nickname: str
    token_status: str
    is_active: bool
    last_verified_at: str | None


@router.get("/accounts/current", response_model=WechatAccountResponse)
async def get_current_wechat_account() -> WechatAccountResponse:
    return WechatAccountResponse(
        id="demo-wechat-account",
        nickname="VaultTech 内容助手",
        token_status="valid",
        is_active=True,
        last_verified_at="2026-06-10T14:48:00+08:00",
    )


@router.post("/accounts/qr-login")
async def create_wechat_qr_login() -> dict[str, str]:
    return {
        "login_id": "demo-login",
        "status": "waiting_scan",
        "qr_url": "about:blank",
    }

