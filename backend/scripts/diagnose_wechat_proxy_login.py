from __future__ import annotations

import argparse
import asyncio
import base64
import json
import time
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import httpx

from app.services.wechat_login_driver import MP_BASE_URL, MP_HEADERS


def emit(event: str, **details: Any) -> None:
    print(json.dumps({"event": event, **details}, ensure_ascii=False), flush=True)


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


async def start_login(client: httpx.AsyncClient) -> None:
    payload = {
        "userlang": "zh_CN",
        "redirect_url": "",
        "login_type": "3",
        "sessionid": f"{int(time.time() * 1000)}{uuid4().hex[:4]}",
        "token": "",
        "lang": "zh_CN",
        "f": "json",
        "ajax": "1",
    }
    response = await client.post(
        f"{MP_BASE_URL}/cgi-bin/bizlogin",
        params={"action": "startlogin"},
        data=payload,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("base_resp", {}).get("ret") != 0:
        raise RuntimeError(data.get("base_resp", {}).get("err_msg") or "startlogin failed")
    if not client.cookies.get("uuid"):
        raise RuntimeError("startlogin did not return uuid cookie")


async def get_qrcode(client: httpx.AsyncClient) -> tuple[bytes, str]:
    response = await client.get(
        f"{MP_BASE_URL}/cgi-bin/scanloginqrcode",
        params={"action": "getqrcode", "random": int(time.time() * 1000)},
    )
    response.raise_for_status()
    if len(response.content) < 500:
        raise RuntimeError("qrcode response is empty")
    return response.content, response.headers.get("content-type", "image/png").split(";")[0]


async def ask_scan_status(client: httpx.AsyncClient) -> dict[str, Any]:
    response = await client.get(
        f"{MP_BASE_URL}/cgi-bin/scanloginqrcode",
        params={
            "action": "ask",
            "token": "",
            "lang": "zh_CN",
            "f": "json",
            "ajax": "1",
        },
    )
    response.raise_for_status()
    return response.json()


async def finish_login(client: httpx.AsyncClient) -> str:
    response = await client.post(
        f"{MP_BASE_URL}/cgi-bin/bizlogin",
        params={"action": "login"},
        data={
            "userlang": "zh_CN",
            "redirect_url": "",
            "cookie_forbidden": "0",
            "cookie_cleaned": "0",
            "plugin_used": "0",
            "login_type": "3",
            "token": "",
            "lang": "zh_CN",
            "f": "json",
            "ajax": "1",
        },
    )
    response.raise_for_status()
    data = response.json()
    redirect_url = data.get("redirect_url")
    if not redirect_url:
        base_resp = data.get("base_resp") or {}
        raise RuntimeError(
            f"login failed: ret={base_resp.get('ret')} err_msg={base_resp.get('err_msg')}"
        )
    token = (parse_qs(urlparse(redirect_url).query).get("token") or [None])[0]
    if not token:
        raise RuntimeError("login redirect_url did not contain token")
    return token


async def test_appmsg(
    client: httpx.AsyncClient, token: str, fakeid: str, count: int
) -> dict[str, Any]:
    started = time.perf_counter()
    response = await client.get(
        f"{MP_BASE_URL}/cgi-bin/appmsg",
        params={
            "action": "list_ex",
            "begin": 0,
            "count": count,
            "fakeid": fakeid,
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
    base_resp = data.get("base_resp") or {}
    return {
        "result": classify(data, response),
        "http_status": response.status_code,
        "final_host": response.url.host,
        "base_ret": base_resp.get("ret"),
        "err_msg": str(base_resp.get("err_msg") or "")[:160],
        "item_count": len(data.get("app_msg_list") or data.get("list") or []),
        "elapsed_ms": round((time.perf_counter() - started) * 1000),
    }


async def run(args: argparse.Namespace) -> int:
    run_id = uuid4().hex[:12]
    timeout = httpx.Timeout(args.timeout, connect=min(10.0, args.timeout))
    emit("starting", run_id=run_id, proxy=args.proxy, writes_database=False)

    async with httpx.AsyncClient(
        headers=MP_HEADERS,
        proxy=args.proxy,
        timeout=timeout,
        follow_redirects=True,
        trust_env=False,
    ) as client:
        await start_login(client)
        image, content_type = await get_qrcode(client)
        print(f"CODEX_QR_BEGIN_{run_id}", flush=True)
        print(base64.b64encode(image).decode("ascii"), flush=True)
        print(f"CODEX_QR_END_{run_id}", flush=True)
        emit("waiting_scan", run_id=run_id, content_type=content_type)

        deadline = time.monotonic() + args.login_timeout
        last_status: Any = None
        while time.monotonic() < deadline:
            scan = await ask_scan_status(client)
            status = scan.get("status")
            if status != last_status:
                emit("scan_status", run_id=run_id, status=status)
                last_status = status
            if status == 1:
                token = await finish_login(client)
                emit("login_confirmed", run_id=run_id)
                result = await test_appmsg(client, token, args.fakeid, args.count)
                emit(
                    "completed",
                    run_id=run_id,
                    proxy=args.proxy,
                    endpoint="appmsg/list_ex",
                    **result,
                )
                return 0 if result["result"] == "success" else 2
            if status in {2, 3}:
                emit("expired", run_id=run_id, status=status)
                return 3
            if status == 5:
                emit("failed", run_id=run_id, reason="wechat_account_has_no_email")
                return 4
            await asyncio.sleep(2)

        emit("expired", run_id=run_id, reason="login_timeout")
        return 3


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="使用同一固定代理完成临时微信扫码登录并测试 appmsg；不写数据库。"
    )
    parser.add_argument("--proxy", required=True, help="例如 http://1.2.3.4:8080")
    parser.add_argument("--fakeid", required=True)
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--login-timeout", type=float, default=300.0)
    args = parser.parse_args()
    try:
        return await run(args)
    except httpx.ProxyError as exc:
        emit("failed", reason="proxy_connect_error", error=type(exc).__name__)
        return 10
    except httpx.TimeoutException as exc:
        emit("failed", reason="timeout", error=type(exc).__name__)
        return 11
    except httpx.HTTPError as exc:
        emit("failed", reason="transport_error", error=type(exc).__name__)
        return 12
    except (RuntimeError, ValueError) as exc:
        emit("failed", reason="wechat_login_error", error=str(exc)[:240])
        return 13


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
