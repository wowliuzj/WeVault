from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.api.v1.endpoints.external import (
    build_date_range,
    require_robottoday_token,
    serialize_external_article,
)
from app.core.config import settings
from app.models.article import Article
from app.models.enums import FetchStatus, SourceFrom, SourceStatus
from app.models.wechat import WechatSource


def test_build_date_range_is_inclusive_of_end_date() -> None:
    start_at, end_before = build_date_range(date(2026, 9, 1), date(2026, 9, 19))

    assert start_at == datetime(2026, 9, 1, tzinfo=UTC)
    assert end_before == datetime(2026, 9, 20, tzinfo=UTC)


def test_build_date_range_rejects_reversed_dates() -> None:
    with pytest.raises(HTTPException) as exc_info:
        build_date_range(date(2026, 9, 20), date(2026, 9, 19))

    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_robottoday_token_must_match(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "robottoday_token", "expected-token")

    await require_robottoday_token(
        HTTPAuthorizationCredentials(scheme="Bearer", credentials="expected-token")
    )

    with pytest.raises(HTTPException) as exc_info:
        await require_robottoday_token(
            HTTPAuthorizationCredentials(scheme="Bearer", credentials="wrong-token")
        )
    assert exc_info.value.status_code == 401


def test_content_field_is_only_set_when_requested() -> None:
    now = datetime.now(UTC)
    source = WechatSource(
        id=uuid4(),
        user_id=uuid4(),
        name="RobotToday",
        source_from=SourceFrom.SEARCH,
        status=SourceStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    article = Article(
        id=uuid4(),
        user_id=source.user_id,
        source_id=source.id,
        title="Test article",
        original_url="https://example.com/article",
        content_status=FetchStatus.FETCHED,
        created_at=now,
        updated_at=now,
    )

    without_content = serialize_external_article(article, source, include_content=False)
    with_content = serialize_external_article(
        article,
        source,
        "<p>正文</p>",
        include_content=True,
    )

    assert "content" not in without_content.model_dump(exclude_unset=True)
    assert with_content.model_dump(exclude_unset=True)["content"] == "<p>正文</p>"
