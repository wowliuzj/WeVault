import httpx
import pytest

from app.services.weread_client import WereadClient, WereadError


@pytest.mark.asyncio
async def test_request_rejects_login_timeout_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get(*args, **kwargs) -> httpx.Response:
        request = httpx.Request("GET", "https://weread.qq.com/web/mp/articles")
        return httpx.Response(
            200,
            request=request,
            json={"errCode": -2012, "errMsg": "登录超时", "info": ""},
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    with pytest.raises(WereadError, match="登录已超时"):
        await WereadClient({"vid": "test", "skey": "test"}).request("/web/mp/articles")


@pytest.mark.asyncio
async def test_fetch_content_accepts_cgi_data_without_js_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    html = "<script>window.cgiDataNew={content_noencode:'<section>正文</section>'}</script>"

    async def fake_request(*args, **kwargs) -> httpx.Response:
        return httpx.Response(200, text=html)

    client = WereadClient({"vid": "test", "skey": "test"})
    monkeypatch.setattr(client, "request", fake_request)

    assert await client.fetch_content("review-id") == html


@pytest.mark.asyncio
async def test_fetch_content_rejects_empty_response(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_request(*args, **kwargs) -> httpx.Response:
        return httpx.Response(200, text="")

    async def fake_sleep(*args, **kwargs) -> None:
        return None

    client = WereadClient({"vid": "test", "skey": "test"})
    monkeypatch.setattr(client, "request", fake_request)
    monkeypatch.setattr("app.services.weread_client.asyncio.sleep", fake_sleep)

    with pytest.raises(WereadError, match="连续返回空内容"):
        await client.fetch_content("review-id")


@pytest.mark.asyncio
async def test_search_mp_keeps_outer_book_id_when_book_info_is_nested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "results": [
            {
                "bookId": "MP_WXS_123",
                "bookInfo": {"title": "测试公众号", "author": "测试作者"},
            }
        ]
    }

    async def fake_request(*args, **kwargs) -> httpx.Response:
        return httpx.Response(200, json=payload)

    client = WereadClient({"vid": "test", "skey": "test"})
    monkeypatch.setattr(client, "request", fake_request)

    assert await client.search_mp("测试公众号") == [
        {
            "bookId": "MP_WXS_123",
            "bookInfo": {"title": "测试公众号", "author": "测试作者"},
            "title": "测试公众号",
            "author": "测试作者",
        }
    ]


@pytest.mark.asyncio
async def test_list_shelf_mps_returns_only_mp_books(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "books": [
            {"bookId": "MP_WXS_123", "title": "测试公众号", "author": "作者"},
            {"bookId": "normal-book", "title": "普通图书"},
        ]
    }

    async def fake_request(*args, **kwargs) -> httpx.Response:
        assert args[0] == "/web/shelf/sync"
        assert kwargs["params"] == {"userVid": "test-vid", "synckey": 0}
        return httpx.Response(200, json=payload)

    client = WereadClient({"vid": "test-vid", "skey": "test-skey"})
    monkeypatch.setattr(client, "request", fake_request)

    assert await client.list_shelf_mps() == [payload["books"][0]]


@pytest.mark.asyncio
async def test_list_shelf_mps_flattens_nested_book_info(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "books": [
            {
                "bookId": "MP_WXS_123",
                "bookInfo": {"title": "测试公众号", "author": "作者"},
            }
        ]
    }

    async def fake_request(*args, **kwargs) -> httpx.Response:
        return httpx.Response(200, json=payload)

    client = WereadClient({"vid": "test-vid", "skey": "test-skey"})
    monkeypatch.setattr(client, "request", fake_request)

    assert await client.list_shelf_mps() == [
        {
            "bookId": "MP_WXS_123",
            "bookInfo": {"title": "测试公众号", "author": "作者"},
            "title": "测试公众号",
            "author": "作者",
        }
    ]


@pytest.mark.asyncio
async def test_fetch_content_retries_empty_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    html = "<div id='js_content'>正文</div>"
    responses = [httpx.Response(200, text=""), httpx.Response(200, text=html)]
    sleeps: list[float] = []

    async def fake_request(*args, **kwargs) -> httpx.Response:
        return responses.pop(0)

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    client = WereadClient({"vid": "test", "skey": "test"})
    monkeypatch.setattr(client, "request", fake_request)
    monkeypatch.setattr("app.services.weread_client.asyncio.sleep", fake_sleep)

    assert await client.fetch_content("review-id") == html
    assert sleeps == [0.8]


def test_credentials_headers_include_complete_cookie_set() -> None:
    from app.services.weread_client import credentials_headers

    headers = credentials_headers(
        {
            "vid": "test-vid",
            "skey": "test-skey",
            "refresh_token": "web@test-refresh",
            "cookies": {"wr_gid": "gid", "wr_fp": "fp"},
        }
    )

    assert headers["x-vid"] == "test-vid"
    assert headers["x-skey"] == "test-skey"
    assert "wr_vid=test-vid" in headers["Cookie"]
    assert "wr_skey=test-skey" in headers["Cookie"]
    assert "wr_rt=web%40test-refresh" in headers["Cookie"]
    assert "wr_gid=gid" in headers["Cookie"]
    assert "wr_fp=fp" in headers["Cookie"]


@pytest.mark.asyncio
async def test_request_renews_cookie_and_retries_once(monkeypatch: pytest.MonkeyPatch) -> None:
    get_calls = 0
    post_calls = 0

    async def fake_get(self, path, **kwargs) -> httpx.Response:
        nonlocal get_calls
        get_calls += 1
        request = httpx.Request("GET", f"https://weread.qq.com{path}")
        if get_calls == 1:
            return httpx.Response(
                200,
                request=request,
                json={"errCode": -2012, "errMsg": "登录超时"},
            )
        assert self.cookies.get("wr_skey") == "renewed-skey"
        return httpx.Response(200, request=request, json={"reviews": []})

    async def fake_post(self, path, **kwargs) -> httpx.Response:
        nonlocal post_calls
        post_calls += 1
        assert path == "/web/login/renewal"
        assert self.cookies.get("wr_rt") == "web%40refresh-token"
        self.cookies.set("wr_skey", "renewed-skey", domain="weread.qq.com", path="/")
        request = httpx.Request("POST", f"https://weread.qq.com{path}")
        return httpx.Response(200, request=request, json={"errCode": 0})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    credentials = {
        "vid": "test-vid",
        "skey": "expired-skey",
        "refresh_token": "web@refresh-token",
        "cookies": {
            "wr_vid": "test-vid",
            "wr_skey": "expired-skey",
            "wr_rt": "web%40refresh-token",
        },
    }

    response = await WereadClient(credentials).request("/web/mp/articles")

    assert response.json() == {"reviews": []}
    assert get_calls == 2
    assert post_calls == 1
    assert credentials["skey"] == "renewed-skey"
    assert credentials["cookies"]["wr_skey"] == "renewed-skey"
