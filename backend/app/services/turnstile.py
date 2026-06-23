import httpx
from fastapi import HTTPException, status

from app.core.config import settings

VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


async def verify_turnstile_token(token: str | None) -> None:
    secret_key = settings.cloudflare_turnstile_secret_key
    if not secret_key:
        return

    if not token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请先完成人机验证。",
        )

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            VERIFY_URL,
            data={
                "secret": secret_key,
                "response": token,
            },
        )

    if response.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="人机验证服务暂时不可用，请稍后重试。",
        )

    result = response.json()
    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="人机验证失败，请刷新后重试。",
        )
