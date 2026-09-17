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

    client = WereadClient({"vid": "test", "skey": "test"})
    monkeypatch.setattr(client, "request", fake_request)

    with pytest.raises(WereadError, match="返回空内容"):
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
