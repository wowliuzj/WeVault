from uuid import uuid4

import pytest

from app.services.weread_browser_session import (
    WereadBrowserSessionManager,
    merge_browser_cookies,
    profile_path,
)
from app.services.weread_client import WereadError


def test_merge_browser_cookies_keeps_existing_and_updates_tokens() -> None:
    credentials = {
        "vid": "old-vid",
        "skey": "old-skey",
        "refresh_token": "old-refresh",
        "cookies": {"wr_gid": "gid", "wr_skey": "old-skey"},
    }

    merged = merge_browser_cookies(
        credentials,
        [
            {"name": "wr_vid", "value": "new-vid"},
            {"name": "wr_skey", "value": "new-skey"},
            {"name": "wr_rt", "value": "web%40new-refresh"},
        ],
    )

    assert merged["cookies"] == {
        "wr_gid": "gid",
        "wr_skey": "new-skey",
        "wr_vid": "new-vid",
        "wr_rt": "web%40new-refresh",
    }
    assert merged["vid"] == "new-vid"
    assert merged["skey"] == "new-skey"
    assert merged["refresh_token"] == "web@new-refresh"
    assert credentials["skey"] == "old-skey"


def test_profile_path_isolated_by_user(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(
        "app.services.weread_browser_session.settings.weread_profile_dir", str(tmp_path)
    )
    first = uuid4()
    second = uuid4()

    assert profile_path(first) == tmp_path / str(first)
    assert profile_path(second) == tmp_path / str(second)
    assert profile_path(first) != profile_path(second)


@pytest.mark.asyncio
async def test_refresh_failure_does_not_save_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = WereadBrowserSessionManager()
    user_id = uuid4()
    session_id = uuid4()
    saved = False
    expired = False

    async def fake_load(_user_id):
        return session_id, {"vid": "vid", "skey": "old"}

    async def fake_find(_user_id):
        return "review-id"

    async def fake_browser(_user_id, credentials, review_id):
        return {**credentials, "skey": "browser-value"}

    async def fake_verify(credentials, review_id):
        raise WereadError("微信读书授权未能恢复公众号文章访问，请重新扫码授权。")

    async def fake_save(*args):
        nonlocal saved
        saved = True

    async def fake_expire(_session_id):
        nonlocal expired
        expired = True

    monkeypatch.setattr(manager, "_load_credentials", fake_load)
    monkeypatch.setattr(manager, "_find_review_id", fake_find)
    monkeypatch.setattr(manager, "_run_browser", fake_browser)
    monkeypatch.setattr(manager, "_verify", fake_verify)
    monkeypatch.setattr(manager, "_save_credentials", fake_save)
    monkeypatch.setattr(manager, "_mark_expired", fake_expire)

    with pytest.raises(WereadError, match="重新扫码授权"):
        await manager.refresh_user(user_id)

    assert saved is False
    assert expired is True


@pytest.mark.asyncio
async def test_keepalive_failure_does_not_mark_session_expired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = WereadBrowserSessionManager()
    user_id = uuid4()
    session_id = uuid4()
    expired = False

    async def fake_load(_user_id):
        return session_id, {"vid": "vid", "skey": "old"}

    async def fake_find(_user_id):
        return "review-id"

    async def fake_browser(_user_id, credentials, review_id):
        return credentials

    async def fake_verify(credentials, review_id):
        raise WereadError("temporary failure")

    async def fake_expire(_session_id):
        nonlocal expired
        expired = True

    monkeypatch.setattr(manager, "_load_credentials", fake_load)
    monkeypatch.setattr(manager, "_find_review_id", fake_find)
    monkeypatch.setattr(manager, "_run_browser", fake_browser)
    monkeypatch.setattr(manager, "_verify", fake_verify)
    monkeypatch.setattr(manager, "_mark_expired", fake_expire)

    with pytest.raises(WereadError, match="temporary"):
        await manager.refresh_user(user_id, mark_expired=False)

    assert expired is False

class _FakeHttpClient:
    def __init__(self, responses, **kwargs):
        self.responses = list(responses)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None

    async def get(self, path, **kwargs):
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_verify_rejects_empty_mp_content(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    manager = WereadBrowserSessionManager()
    responses = [httpx.Response(200, text="")]
    monkeypatch.setattr(
        "app.services.weread_browser_session.httpx.AsyncClient",
        lambda **kwargs: _FakeHttpClient(responses, **kwargs),
    )

    with pytest.raises(WereadError, match="未能恢复公众号文章访问"):
        await manager._verify({"vid": "vid", "skey": "skey"}, "review-id")


@pytest.mark.asyncio
async def test_verify_accepts_mp_content_with_article_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    manager = WereadBrowserSessionManager()
    responses = [
        httpx.Response(200, text='<div id="js_content">正文</div>'),
        httpx.Response(200, json={"name": "测试用户"}),
    ]
    monkeypatch.setattr(
        "app.services.weread_browser_session.httpx.AsyncClient",
        lambda **kwargs: _FakeHttpClient(responses, **kwargs),
    )

    assert await manager._verify(
        {"vid": "vid", "skey": "skey"}, "review-id"
    ) == {"name": "测试用户"}
