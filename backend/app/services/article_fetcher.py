from __future__ import annotations

import ast
import hashlib
import re
from datetime import UTC, datetime
from html import escape, unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, TypedDict
from urllib.parse import urljoin

import httpx
from playwright.async_api import async_playwright
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.article import Article, ArticleContent
from app.models.enums import FetchStatus
from app.services.article_assets import (
    IMAGE_EXTENSIONS,
    is_allowed_wechat_image_url,
    normalize_image_url,
)
from app.services.wechat_login_driver import MP_HEADERS, wechat_login_manager

ARTICLE_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 "
    "MicroMessenger/6.8.0 NetType/WIFI"
)


class ArticleFetchError(RuntimeError):
    pass


class BrowserArticlePage(TypedDict):
    html: str
    content_html: str | None
    cookies: list[dict[str, Any]]


class PlainTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"br", "p", "div", "section", "li", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self.parts.append(text)

    def text(self) -> str:
        value = " ".join(self.parts)
        value = re.sub(r"[ \t\r\f\v]+", " ", value)
        value = re.sub(r"\n\s*", "\n", value)
        value = re.sub(r"\n{3,}", "\n\n", value)
        return value.strip()


def html_to_text(html: str) -> str:
    parser = PlainTextExtractor()
    parser.feed(html)
    return parser.text()


def text_to_markdown(text: str) -> str:
    paragraphs = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n\n".join(paragraphs)


def extract_meta_content(html: str, property_name: str) -> str | None:
    pattern = (
        r'<meta[^>]+property=["\']'
        + re.escape(property_name)
        + r'["\'][^>]+content=["\'](?P<content>[^"\']*)["\']'
    )
    match = re.search(pattern, html, flags=re.IGNORECASE)
    if not match:
        return None
    return unescape(match.group("content")).strip() or None


def extract_js_value(html: str, name: str) -> str | None:
    patterns = [
        rf"window\.{re.escape(name)}\s*=\s*['\"](?P<value>[^'\"]*)['\"]",
        rf"var\s+{re.escape(name)}\s*=\s*['\"](?P<value>[^'\"]*)['\"]",
    ]
    for pattern in patterns:
        match = re.search(pattern, html)
        if match:
            value = unescape(match.group("value")).strip()
            if value:
                return value
    return None


def decode_js_string(value: str) -> str:
    try:
        return str(ast.literal_eval(f"'{value}'"))
    except (SyntaxError, ValueError):
        return value.encode("utf-8").decode("unicode_escape", errors="ignore")


def extract_jsdecode_field(html: str, name: str) -> str | None:
    pattern = rf"\b{re.escape(name)}\s*:\s*JsDecode\('(?P<value>(?:\\.|[^'\\])*)'\)"
    match = re.search(pattern, html, flags=re.DOTALL)
    if not match:
        return None
    value = unescape(decode_js_string(match.group("value"))).strip()
    return value or None


def extract_element_html(html: str, element_id: str) -> str | None:
    start_match = re.search(
        rf"<(?P<tag>[a-zA-Z0-9]+)(?P<attrs>[^>]*\bid\s*=\s*[\"']?"
        rf"{re.escape(element_id)}[\"']?[^>]*)>",
        html,
        flags=re.IGNORECASE,
    )
    if not start_match:
        return None

    tag = start_match.group("tag").lower()
    content_start = start_match.end()
    depth = 1
    tag_pattern = re.compile(rf"</?{re.escape(tag)}\b[^>]*>", flags=re.IGNORECASE)
    for match in tag_pattern.finditer(html, content_start):
        token = match.group(0)
        if token.startswith("</"):
            depth -= 1
            if depth == 0:
                return html[content_start : match.start()].strip()
        elif not token.endswith("/>"):
            depth += 1
    fallback_markers = [
        r"<script\b",
        r"<div\b[^>]*\bid\s*=\s*[\"']?js_sg_bar[\"']?",
        r"<div\b[^>]*\bid\s*=\s*[\"']?js_pc_qr_code[\"']?",
        r"<div\b[^>]*\bclass\s*=\s*[\"'][^\"']*rich_media_tool",
    ]
    marker_positions = [
        match.start()
        for pattern in fallback_markers
        if (match := re.search(pattern, html[content_start:], flags=re.IGNORECASE))
    ]
    if marker_positions:
        return html[content_start : content_start + min(marker_positions)].strip()
    return None


def extract_article_content_html(raw_html: str) -> str | None:
    dom_content = extract_element_html(raw_html, "js_content") or extract_element_html(
        raw_html,
        "js_article",
    )
    if dom_content:
        return dom_content

    return extract_cgi_data_content_html(raw_html)


def extract_cgi_data_content_html(raw_html: str) -> str | None:
    if "window.cgiDataNew" not in raw_html:
        return None

    content = extract_jsdecode_field(raw_html, "content_noencode")
    if content:
        return content

    title = extract_jsdecode_field(raw_html, "title")
    if title:
        return f"<section><p>{escape(title)}</p></section>"

    return None


def extract_attr_value(attrs: str, name: str) -> str | None:
    match = re.search(
        rf"\b{re.escape(name)}\s*=\s*(?P<quote>[\"'])(?P<value>.*?)(?P=quote)",
        attrs,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    return unescape(match.group("value")).strip() or None


def remove_attrs(attrs: str, names: set[str]) -> str:
    for name in names:
        attrs = re.sub(
            rf"\s+\b{re.escape(name)}\s*=\s*([\"']).*?\1",
            "",
            attrs,
            flags=re.IGNORECASE | re.DOTALL,
        )
    return attrs


def normalize_image_sources(content_html: str) -> str:
    def replace_img(match: re.Match[str]) -> str:
        attrs = match.group("attrs")
        image_url = (
            extract_attr_value(attrs, "data-src")
            or extract_attr_value(attrs, "data-original")
            or extract_attr_value(attrs, "src")
        )
        normalized_url = normalize_image_url(image_url)
        if not normalized_url:
            return match.group(0)

        cleaned_attrs = remove_attrs(attrs, {"src", "data-src", "data-original"})
        return f'<img{cleaned_attrs} src="{escape(normalized_url, quote=True)}">'

    return re.sub(
        r"<img\b(?P<attrs>[^>]*)>",
        replace_img,
        content_html,
        flags=re.IGNORECASE | re.DOTALL,
    )


def clean_article_html(content_html: str) -> str:
    html = normalize_image_sources(content_html)
    html = re.sub(r"\sstyle=(['\"]).*?\1", "", html, flags=re.IGNORECASE | re.DOTALL)
    html = re.sub(r"\son[a-z]+=(['\"]).*?\1", "", html, flags=re.IGNORECASE | re.DOTALL)
    return html.strip()


async def cache_article_content_images(
    client: httpx.AsyncClient,
    article: Article,
    html: str,
) -> tuple[str, list[dict[str, Any]]]:
    storage_root = Path(settings.asset_storage_dir)
    downloaded: dict[str, dict[str, Any]] = {}

    async def cache_image(image_url: str) -> dict[str, Any] | None:
        normalized_url = normalize_image_url(urljoin(article.original_url, image_url))
        if not normalized_url or not is_allowed_wechat_image_url(normalized_url):
            return None
        if normalized_url in downloaded:
            return downloaded[normalized_url]

        try:
            response = await client.get(normalized_url, headers={"Referer": article.original_url})
            response.raise_for_status()
        except httpx.HTTPError:
            return None

        content_type = response.headers.get("content-type", "image/jpeg").split(";")[0]
        if not content_type.startswith("image/") or len(response.content) > 8 * 1024 * 1024:
            return None

        extension = IMAGE_EXTENSIONS.get(content_type, ".jpg")
        filename = f"{hashlib.sha256(normalized_url.encode()).hexdigest()[:24]}{extension}"
        relative_path = Path("article-assets") / str(article.id) / filename
        asset_file = storage_root / relative_path
        asset_file.parent.mkdir(parents=True, exist_ok=True)
        asset_file.write_bytes(response.content)

        asset = {
            "original_url": normalized_url,
            "storage_path": relative_path.as_posix(),
            "asset_url": f"/api/v1/articles/{article.id}/assets/{filename}",
            "content_type": content_type,
            "size": len(response.content),
        }
        downloaded[normalized_url] = asset
        return asset

    image_pattern = re.compile(
        r"(?P<prefix><img\b[^>]*\bsrc\s*=\s*)(?P<quote>[\"'])(?P<src>.*?)(?P=quote)",
        flags=re.IGNORECASE | re.DOTALL,
    )
    parts: list[str] = []
    cursor = 0
    assets: list[dict[str, Any]] = []
    for match in image_pattern.finditer(html):
        parts.append(html[cursor : match.start()])
        source_url = unescape(match.group("src")).strip()
        asset = await cache_image(source_url)
        if asset is None:
            parts.append(match.group(0))
        else:
            parts.append(
                f"{match.group('prefix')}{match.group('quote')}"
                f"{asset['asset_url']}{match.group('quote')}"
            )
            assets.append(asset)
        cursor = match.end()

    if not parts:
        return html, []

    parts.append(html[cursor:])
    return "".join(parts), assets


def article_headers(cookies: list[dict[str, Any]] | None = None) -> dict[str, str]:
    headers = {
        **MP_HEADERS,
        "User-Agent": ARTICLE_USER_AGENT,
        "Referer": "https://mp.weixin.qq.com/",
    }
    if cookies:
        headers["Cookie"] = wechat_login_manager._cookie_header(cookies)
    return headers


def to_playwright_cookies(cookies: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    playwright_cookies: list[dict[str, Any]] = []
    for cookie in cookies or []:
        name = cookie.get("name")
        value = cookie.get("value")
        if not name or not value or value == "EXPIRED":
            continue
        item: dict[str, Any] = {
            "name": str(name),
            "value": str(value),
            "domain": cookie.get("domain") or "mp.weixin.qq.com",
            "path": cookie.get("path") or "/",
        }
        expires = cookie.get("expires")
        if isinstance(expires, (int, float)) and expires > 0:
            item["expires"] = expires
        playwright_cookies.append(item)
    return playwright_cookies


async def fetch_article_page_with_browser(
    article: Article,
    *,
    cookies: list[dict[str, Any]] | None,
) -> BrowserArticlePage:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=settings.wechat_browser_headless)
        try:
            context = await browser.new_context(
                user_agent=ARTICLE_USER_AGENT,
                viewport={"width": 390, "height": 900},
                device_scale_factor=2,
                is_mobile=True,
            )
            browser_cookies = to_playwright_cookies(cookies)
            if browser_cookies:
                await context.add_cookies(browser_cookies)

            page = await context.new_page()
            await page.goto(article.original_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)
            for _ in range(5):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(400)

            html = await page.content()
            content_html = None
            for selector in ("#js_content", "#js_article"):
                try:
                    locator = page.locator(selector)
                    if await locator.count():
                        value = await locator.first.inner_html(timeout=3000)
                        if value:
                            content_html = value
                            break
                except Exception:
                    continue

            captured_cookies = [
                {
                    "name": cookie["name"],
                    "value": cookie["value"],
                    "domain": cookie.get("domain"),
                    "path": cookie.get("path"),
                    "expires": cookie.get("expires"),
                }
                for cookie in await context.cookies()
                if cookie.get("name") and cookie.get("value")
            ]
            return {
                "html": html,
                "content_html": content_html,
                "cookies": captured_cookies,
            }
        finally:
            await browser.close()


async def fetch_article_html(
    client: httpx.AsyncClient,
    article: Article,
) -> str:
    response = await client.get(article.original_url)
    response.raise_for_status()
    html = response.text
    body_text = html_to_text(html)
    blocked_messages = [
        "当前环境异常，完成验证后即可继续访问",
        "该内容已被发布者删除",
        "The content has been deleted by the author.",
        "内容审核中",
        "该内容暂时无法查看",
        "违规无法查看",
        "Unable to view this content because it violates regulation",
        "发送失败无法查看",
    ]
    for message in blocked_messages:
        if message in body_text:
            raise ArticleFetchError(message)
    return html


async def fetch_article_content(
    db: AsyncSession,
    article: Article,
    *,
    cookies: list[dict[str, Any]] | None,
) -> None:
    article.content_status = FetchStatus.RUNNING
    await db.commit()

    try:
        fetch_cookies = cookies
        async with httpx.AsyncClient(
            headers=article_headers(cookies),
            timeout=httpx.Timeout(25.0, connect=10.0),
            follow_redirects=True,
        ) as client:
            raw_html = await fetch_article_html(client, article)
            content_html = extract_article_content_html(raw_html)

        if not content_html:
            browser_page = await fetch_article_page_with_browser(article, cookies=cookies)
            raw_html = browser_page["html"]
            content_html = browser_page["content_html"] or extract_article_content_html(raw_html)
            fetch_cookies = browser_page["cookies"]

        if not content_html:
            raise ArticleFetchError("没有在文章页中找到正文内容。")

        clean_html = clean_article_html(content_html)
        async with httpx.AsyncClient(
            headers=article_headers(fetch_cookies),
            timeout=httpx.Timeout(25.0, connect=10.0),
            follow_redirects=True,
        ) as asset_client:
            clean_html, content_assets = await cache_article_content_images(
                asset_client,
                article,
                clean_html,
            )

        plain_text = html_to_text(clean_html)
        markdown = text_to_markdown(plain_text)

        result = await db.execute(
            select(ArticleContent).where(ArticleContent.article_id == article.id)
        )
        content = result.scalar_one_or_none()
        if content is None:
            content = ArticleContent(article_id=article.id)
            db.add(content)

        content.raw_html = raw_html
        content.clean_html = clean_html
        content.markdown = markdown
        content.plain_text = plain_text
        content.assets_manifest = {
            "source": "mp.weixin.qq.com",
            "fetched_by": "httpx",
            "assets": content_assets,
        }
        content.fetched_at = datetime.now(UTC)

        article.title = extract_meta_content(raw_html, "og:title") or article.title
        article.author = extract_meta_content(raw_html, "og:article:author") or article.author
        article.digest = extract_meta_content(raw_html, "og:description") or article.digest
        article.content_status = FetchStatus.FETCHED
        await db.commit()
    except Exception:
        article.content_status = FetchStatus.FAILED
        await db.commit()
        raise
