from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.api.v1.endpoints import articles as article_endpoints
from app.services import article_assets


class FakeDb:
    def __init__(self) -> None:
        self.executed = []
        self.deleted = []
        self.committed = False

    async def execute(self, statement):
        self.executed.append(statement)
        return None

    async def delete(self, value) -> None:
        self.deleted.append(value)

    async def commit(self) -> None:
        self.committed = True


def test_delete_article_files_removes_cover_and_content_assets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    article_id = uuid4()
    cover_path = Path("article-covers") / f"{article_id}.jpg"
    cover_file = tmp_path / cover_path
    cover_file.parent.mkdir(parents=True)
    cover_file.write_bytes(b"cover")
    asset_dir = tmp_path / "article-assets" / str(article_id)
    asset_dir.mkdir(parents=True)
    (asset_dir / "image.png").write_bytes(b"image")
    monkeypatch.setattr(article_assets.settings, "asset_storage_dir", str(tmp_path))
    article = SimpleNamespace(id=article_id, cover_storage_path=cover_path.as_posix())

    article_assets.delete_article_files(article)

    assert not cover_file.exists()
    assert not asset_dir.exists()


@pytest.mark.asyncio
async def test_permanently_delete_article_requires_trash_and_removes_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    article = SimpleNamespace(id=uuid4())
    db = FakeDb()
    validation_calls = []
    deleted_files = []

    async def fake_validate(db_arg, user, article_ids, *, deleted=False):
        validation_calls.append((db_arg, article_ids, deleted))
        return [article]

    monkeypatch.setattr(article_endpoints, "validate_user_articles", fake_validate)
    monkeypatch.setattr(article_endpoints, "delete_article_files", deleted_files.append)

    response = await article_endpoints.permanently_delete_article(
        article.id,
        current_user=object(),
        db=db,
    )

    assert response == {"ok": True}
    assert validation_calls == [(db, [article.id], True)]
    assert len(db.executed) == 1
    assert db.deleted == [article]
    assert db.committed is True
    assert deleted_files == [article]


@pytest.mark.asyncio
async def test_permanently_delete_articles_removes_all_selected_trash_articles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    articles = [SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4())]
    db = FakeDb()
    deleted_files = []

    async def fake_validate(db_arg, user, article_ids, *, deleted=False):
        assert db_arg is db
        assert article_ids == [article.id for article in articles]
        assert deleted is True
        return articles

    monkeypatch.setattr(article_endpoints, "validate_user_articles", fake_validate)
    monkeypatch.setattr(article_endpoints, "delete_article_files", deleted_files.append)
    payload = article_endpoints.ArticleBatchRequest(
        article_ids=[article.id for article in articles]
    )

    response = await article_endpoints.permanently_delete_articles(
        payload,
        current_user=object(),
        db=db,
    )

    assert response == {"deleted": 2}
    assert len(db.executed) == 2
    assert db.committed is True
    assert deleted_files == articles
