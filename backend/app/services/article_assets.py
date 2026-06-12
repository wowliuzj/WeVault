from __future__ import annotations

from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.models.article import Article
from app.services.wechat_login_driver import MP_HEADERS, wechat_login_manager


class ArticleAssetError(RuntimeError):
    pass


IMAGE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


def normalize_image_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    image_url = unescape(value).strip()
    if not image_url:
        return None
    if image_url.startswith("//"):
        return f"https:{image_url}"
    if image_url.startswith("http://"):
        return f"https://{image_url.removeprefix('http://')}"
    return image_url


def is_allowed_wechat_image_url(value: str) -> bool:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        return False
    hostname = parsed.hostname or ""
    return (
        hostname == "mp.weixin.qq.com"
        or hostname.endswith(".qpic.cn")
        or hostname.endswith(".qlogo.cn")
        or hostname.endswith(".qq.com")
    )


def get_article_cover_file(article: Article) -> Path:
    if not article.cover_storage_path:
        raise ArticleAssetError("文章还没有本地封面缓存。")

    storage_root = Path(settings.asset_storage_dir).resolve()
    cover_file = (storage_root / article.cover_storage_path).resolve()
    if not cover_file.is_relative_to(storage_root):
        raise ArticleAssetError("封面缓存路径异常。")
    if not cover_file.is_file():
        raise ArticleAssetError("文章本地封面文件不存在。")
    return cover_file


def get_article_content_asset_file(article: Article, asset_name: str) -> Path:
    if "/" in asset_name or "\\" in asset_name or asset_name in {"", ".", ".."}:
        raise ArticleAssetError("文章资源路径异常。")

    storage_root = Path(settings.asset_storage_dir).resolve()
    asset_file = (storage_root / "article-assets" / str(article.id) / asset_name).resolve()
    if not asset_file.is_relative_to(storage_root):
        raise ArticleAssetError("文章资源路径异常。")
    if not asset_file.is_file():
        raise ArticleAssetError("文章本地资源不存在。")
    return asset_file


def delete_article_cover_file(article: Article) -> None:
    if not article.cover_storage_path:
        return

    try:
        cover_file = get_article_cover_file(article)
    except ArticleAssetError:
        article.cover_storage_path = None
        article.cover_content_type = None
        return

    cover_file.unlink(missing_ok=True)
    article.cover_storage_path = None
    article.cover_content_type = None


async def cache_article_cover(
    article: Article,
    *,
    cookies: list[dict[str, Any]] | None = None,
) -> bool:
    cover_url = normalize_image_url(article.cover_url)
    if not cover_url or not is_allowed_wechat_image_url(cover_url):
        return False

    headers = {**MP_HEADERS}
    if cookies:
        headers["Cookie"] = wechat_login_manager._cookie_header(cookies)

    try:
        async with httpx.AsyncClient(
            headers=headers,
            timeout=httpx.Timeout(12.0, connect=6.0),
            follow_redirects=True,
        ) as client:
            response = await client.get(cover_url)
            response.raise_for_status()
    except httpx.HTTPError:
        return False

    content_type = response.headers.get("content-type", "image/jpeg").split(";")[0]
    if not content_type.startswith("image/") or len(response.content) > 4 * 1024 * 1024:
        return False

    extension = IMAGE_EXTENSIONS.get(content_type, ".jpg")
    relative_path = Path("article-covers") / f"{article.id}{extension}"
    cover_file = Path(settings.asset_storage_dir) / relative_path
    cover_file.parent.mkdir(parents=True, exist_ok=True)
    cover_file.write_bytes(response.content)

    article.cover_storage_path = relative_path.as_posix()
    article.cover_content_type = content_type
    return True
