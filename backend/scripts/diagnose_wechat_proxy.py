from __future__ import annotations

import argparse
import asyncio
import json
import time
from typing import Any

import httpx
from sqlalchemy import select

from app.db.session import AsyncSessionLocal, engine
from app.models.user import User
from app.models.wechat import WechatSource
from app.services.sources import get_active_authorized_session
from app.services.wechat_login_driver import MP_BASE_URL, MP_HEADERS, wechat_login_manager


def classify(data: dict[str, Any], response: httpx.Response) -> str:
    if response.url.host != "mp.weixin.qq.com":
        return "redirected"
    base_resp = data.get("base_resp") or {}
    ret = base_resp.get("ret")
    message = str(base_resp.get("err_msg") or "").lower()
    if ret in (0, "0", None):
        return "success"
    if "freq control" in message:
        return "frequency_limited"
    if any(word in message for word in ("login", "token", "登录", "invalid", "expired")):
        return "login_expired"
    return "wechat_api_error"


async def run(args: argparse.Namespace) -> int:
    async with AsyncSessionLocal() as db:
        user = (
            await db.execute(select(User).where(User.email.ilike(args.user_email.strip())))
        ).scalar_one_or_none()
        if user is None:
            raise RuntimeError("用户不存在。")

        source = (
            await db.execute(
                select(WechatSource).where(
                    WechatSource.id == args.source_id,
                    WechatSource.user_id == user.id,
                    WechatSource.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if source is None:
            raise RuntimeError("公众号源不存在或不属于该用户。")
        if not source.fakeid:
            raise RuntimeError("公众号源缺少 fakeid。")

        account, _, cookies, token = await get_active_authorized_session(db, user)
        headers = {**MP_HEADERS, "Cookie": wechat_login_manager._cookie_header(cookies)}
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(
                headers=headers,
                proxy=args.proxy,
                timeout=httpx.Timeout(args.timeout, connect=min(10.0, args.timeout)),
                follow_redirects=True,
                trust_env=False,
            ) as client:
                response = await client.get(
                    f"{MP_BASE_URL}/cgi-bin/appmsg",
                    params={
                        "action": "list_ex",
                        "begin": 0,
                        "count": 5,
                        "fakeid": source.fakeid,
                        "type": "9",
                        "query": "",
                        "token": token,
                        "lang": "zh_CN",
                        "f": "json",
                        "ajax": "1",
                    },
                )
                response.raise_for_status()
                data = response.json()
        except httpx.ProxyError as exc:
            result = {"result": "proxy_connect_error", "error": type(exc).__name__}
        except httpx.TimeoutException as exc:
            result = {"result": "timeout", "error": type(exc).__name__}
        except httpx.HTTPError as exc:
            result = {"result": "transport_error", "error": type(exc).__name__}
        except ValueError:
            result = {"result": "invalid_json"}
        else:
            base_resp = data.get("base_resp") or {}
            result = {
                "result": classify(data, response),
                "http_status": response.status_code,
                "final_host": response.url.host,
                "base_ret": base_resp.get("ret"),
                "err_msg": str(base_resp.get("err_msg") or "")[:160],
                "item_count": len(data.get("app_msg_list") or data.get("list") or []),
            }

        result.update(
            {
                "mode": "proxy" if args.proxy else "direct",
                "endpoint": "appmsg/list_ex",
                "elapsed_ms": round((time.perf_counter() - started) * 1000),
                "user": user.email,
                "source_id": str(source.id),
                "source_name": source.name,
                "account": account.nickname,
            }
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result["result"] == "success" else 2


async def main() -> int:
    parser = argparse.ArgumentParser(description="低频诊断微信公众号列表接口的直连/代理结果。")
    parser.add_argument("--user-email", required=True)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--proxy", help="HTTP CONNECT 代理，例如 http://1.2.3.4:8080")
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()
    try:
        return await run(args)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
