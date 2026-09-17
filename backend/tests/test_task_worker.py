from types import SimpleNamespace

import pytest

from app.services import task_worker


class FakeDb:
    async def commit(self) -> None:
        return None


@pytest.mark.asyncio
async def test_weread_list_only_does_not_fetch_article_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = SimpleNamespace(last_used_at=None)
    saved: list[dict] = []

    async def fake_get_session(db, user):
        return session, {"vid": "test", "skey": "test"}

    class FakeClient:
        def __init__(self, credentials):
            pass

        async def list_articles(self, book_id: str, offset: int):
            return [
                {
                    "reviewId": "MP_WXS_123_review",
                    "originalId": "review",
                    "title": "测试文章",
                    "mp_name": "测试公众号",
                    "content": "摘要",
                    "time": None,
                }
            ]

        async def fetch_content(self, review_id: str) -> str:
            raise AssertionError("list-only fetch must not request article content")

    async def fake_upsert_article(db, source, account_id, article_data, **kwargs):
        saved.append(article_data)
        return None

    monkeypatch.setattr(task_worker, "get_active_weread_session", fake_get_session)
    monkeypatch.setattr(task_worker, "WereadClient", FakeClient)
    monkeypatch.setattr(task_worker, "upsert_article", fake_upsert_article)

    task = SimpleNamespace(
        payload={"fetch_content": False, "skip_existing": True, "limit": 1},
        progress_current=0,
        progress_total=0,
    )
    source = SimpleNamespace(
        weread_book_id="MP_WXS_123",
        wechat_account_id=None,
        biz=None,
        last_content_fetched_at=None,
        last_list_fetched_at=None,
    )

    await task_worker._fetch_source_articles_weread(FakeDb(), task, source, object())

    assert saved[0]["weread_review_id"] == "MP_WXS_123_review"
    # This endpoint is retained only as an internal marker until the real
    # mp.weixin.qq.com URL is lazily resolved; it must never be opened directly.
    assert saved[0]["original_url"] == (
        "https://weread.qq.com/web/mp/content?reviewId=MP_WXS_123_review"
    )
