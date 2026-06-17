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


class CleanArticleResult(TypedDict):
    html: str
    media: list[dict[str, Any]]


class PlainTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"br", "p", "div", "section", "aside", "li", "h1", "h2", "h3"}:
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


MEDIA_EXPLICIT_TAGS = (
    "audio",
    "iframe",
    "mp-common-mpaudio",
    "mp-common-mpvideo",
    "mpvoice",
    "mpvideo",
    "qqmusic",
    "video",
)
MEDIA_CONTAINER_MARKERS = (
    "audio",
    "insertvideo",
    "js_editor_qqmusic",
    "js_tx_video",
    "mpaudio",
    "mpvoice",
    "mpvideo",
    "music",
    "qqmusic",
    "video_iframe",
    "wx_video",
)
MEDIA_TITLE_ATTRS = (
    "data-title",
    "data-songname",
    "data-name",
    "data-video-title",
    "name",
    "title",
    "aria-label",
    "songname",
)
MEDIA_ARTIST_ATTRS = (
    "data-singer",
    "data-artist",
    "data-author",
    "data-source",
    "data-nickname",
    "singer",
    "artist",
    "author",
)
MEDIA_COVER_ATTRS = (
    "data-albumurl",
    "data-cover",
    "data-coverurl",
    "data-headimgurl",
    "data-img",
    "data-thumb",
    "poster",
)
MEDIA_SOURCE_ATTRS = (
    "data-src",
    "data-url",
    "data-link",
    "data-videourl",
    "data-musicurl",
    "href",
    "src",
)
MEDIA_ID_ATTRS = (
    "data-mid",
    "data-musicid",
    "data-vid",
    "data-mpvid",
    "musicid",
    "vid",
    "voice_encode_fileid",
)
MEDIA_BLOCK_TAGS = "|".join(re.escape(tag) for tag in MEDIA_EXPLICIT_TAGS)
MEDIA_CONTAINER_PATTERN = "|".join(re.escape(marker) for marker in MEDIA_CONTAINER_MARKERS)
MEDIA_EXPLICIT_BLOCK_RE = re.compile(
    rf"<(?P<tag>{MEDIA_BLOCK_TAGS})\b(?P<attrs>[^>]*)>(?P<body>.*?)</(?P=tag)>",
    flags=re.IGNORECASE | re.DOTALL,
)
MEDIA_CONTAINER_BLOCK_RE = re.compile(
    rf"<(?P<tag>section|div)\b(?P<attrs>[^>]*(?:{MEDIA_CONTAINER_PATTERN})[^>]*)>"
    rf"(?P<body>.*?)</(?P=tag)>",
    flags=re.IGNORECASE | re.DOTALL,
)
MEDIA_SELF_RE = re.compile(
    rf"<(?P<tag>{MEDIA_BLOCK_TAGS})\b(?P<attrs>[^>]*)/?>",
    flags=re.IGNORECASE | re.DOTALL,
)
ATTR_RE = re.compile(
    r"(?P<name>[\w:-]+)(?:\s*=\s*(?:(?P<quote>[\"'])(?P<quoted>.*?)(?P=quote)|"
    r"(?P<bare>[^\s\"'=<>`]+)))?",
    flags=re.DOTALL,
)


def compact_text(value: str | None) -> str | None:
    if not value:
        return None
    text = unescape(value).strip()
    text = re.sub(r"\s+", " ", text)
    return text or None


def extract_attrs(attrs: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for match in ATTR_RE.finditer(attrs):
        name = match.group("name").lower()
        value = match.group("quoted") if match.group("quote") else match.group("bare")
        values[name] = compact_text(value) or ""
    return values


def first_attr(attrs: dict[str, str], names: tuple[str, ...]) -> str | None:
    for name in names:
        value = compact_text(attrs.get(name))
        if value:
            return value
    return None


def extract_js_like_value(html: str, names: tuple[str, ...]) -> str | None:
    value_html = unescape(html)
    for name in names:
        patterns = [
            rf"[\"']{re.escape(name)}[\"']\s*:\s*(?P<quote>[\"'])(?P<value>.*?)(?P=quote)",
            rf"\b{re.escape(name)}\s*=\s*(?P<quote>[\"'])(?P<value>.*?)(?P=quote)",
        ]
        for pattern in patterns:
            match = re.search(pattern, value_html, flags=re.IGNORECASE | re.DOTALL)
            if match:
                value = compact_text(decode_js_string(match.group("value")))
                if value:
                    return value
    return None


def media_url(article_url: str, value: str | None) -> str | None:
    url = compact_text(value)
    if not url or url.startswith(("data:", "javascript:")):
        return None
    if url.startswith("//"):
        return f"https:{url}"
    return urljoin(article_url, url) if article_url else url


def detect_media_type(tag: str, attrs: dict[str, str], body: str) -> str:
    blob = " ".join([tag, *attrs.keys(), *attrs.values(), body[:500]]).lower()
    if any(marker in blob for marker in ("video", "mpvideo", "iframe", "vid")):
        return "video"
    if any(marker in blob for marker in ("audio", "music", "mpvoice", "qqmusic", "song")):
        return "music"
    return "media"


def is_media_candidate(tag: str, attrs: dict[str, str], body: str) -> bool:
    if tag.lower() in MEDIA_EXPLICIT_TAGS:
        return True
    blob = " ".join([tag, *attrs.keys(), *attrs.values(), body[:500]]).lower()
    return any(marker in blob for marker in MEDIA_CONTAINER_MARKERS)


def build_media_item(
    tag: str,
    attrs_text: str,
    body: str,
    *,
    article_url: str,
    position: str,
) -> dict[str, Any] | None:
    attrs = extract_attrs(attrs_text)
    if not is_media_candidate(tag, attrs, body):
        return None

    body_text = compact_text(html_to_text(body))
    media_type = detect_media_type(tag, attrs, body)
    title = (
        first_attr(attrs, MEDIA_TITLE_ATTRS)
        or extract_js_like_value(body, ("songname", "title", "name", "video_title"))
        or (body_text if body_text and len(body_text) <= 120 else None)
    )
    artist = first_attr(attrs, MEDIA_ARTIST_ATTRS) or extract_js_like_value(
        body,
        ("singer", "artist", "author", "source", "nickname"),
    )
    cover_url = media_url(
        article_url,
        first_attr(attrs, MEDIA_COVER_ATTRS)
        or extract_js_like_value(body, ("albumurl", "cover", "cover_url", "poster")),
    )
    source_url = media_url(
        article_url,
        first_attr(attrs, MEDIA_SOURCE_ATTRS)
        or extract_js_like_value(body, ("src", "url", "video_url", "music_url")),
    )
    media_id = first_attr(attrs, MEDIA_ID_ATTRS) or extract_js_like_value(
        body,
        ("musicid", "vid", "mpvid", "mid"),
    )

    if not any([title, artist, cover_url, source_url, media_id]):
        return None

    raw_attrs = {key: value for key, value in attrs.items() if value and len(value) <= 500}
    if len(raw_attrs) > 20:
        raw_attrs = dict(list(raw_attrs.items())[:20])

    return {
        "type": media_type,
        "title": title,
        "artist": artist,
        "cover_url": cover_url,
        "source_url": source_url or article_url,
        "media_id": media_id,
        "position": position,
        "raw_attrs": raw_attrs,
    }


def media_signature(media: dict[str, Any]) -> str:
    values = [
        media.get("type"),
        media.get("media_id"),
        media.get("title"),
        media.get("artist"),
        media.get("source_url"),
    ]
    return "|".join(str(value or "").strip().lower() for value in values)


def add_unique_media(items: list[dict[str, Any]], media: dict[str, Any]) -> None:
    signature = media_signature(media)
    if signature and all(media_signature(item) != signature for item in items):
        items.append(media)


def media_label(media_type: str) -> str:
    return {"music": "音乐", "video": "视频"}.get(media_type, "媒体")


def render_media_card(media: dict[str, Any], article_url: str) -> str:
    label = media_label(str(media.get("type") or "media"))
    title = compact_text(str(media.get("title") or "")) or f"未命名{label}"
    artist = compact_text(str(media.get("artist") or ""))
    source_url = compact_text(str(media.get("source_url") or "")) or article_url
    meta_html = f'<div class="wevault-media-meta">{escape(artist)}</div>' if artist else ""
    return (
        f'<aside class="wevault-media-card" data-media-type="{escape(label, quote=True)}">'
        f'<div class="wevault-media-label">{escape(label)}</div>'
        f'<div class="wevault-media-title">{escape(title)}</div>'
        f"{meta_html}"
        f'<a class="wevault-media-link" href="{escape(source_url, quote=True)}" '
        f'target="_blank" rel="noreferrer">打开原文播放：{escape(source_url)}</a>'
        "</aside>"
    )


def replace_media_elements(content_html: str, article_url: str) -> tuple[str, list[dict[str, Any]]]:
    media_items: list[dict[str, Any]] = []

    def replace_block(match: re.Match[str]) -> str:
        media = build_media_item(
            match.group("tag"),
            match.group("attrs"),
            match.groupdict().get("body") or "",
            article_url=article_url,
            position="content",
        )
        if not media:
            return match.group(0)
        add_unique_media(media_items, media)
        return render_media_card(media, article_url)

    html = MEDIA_CONTAINER_BLOCK_RE.sub(replace_block, content_html)
    html = MEDIA_EXPLICIT_BLOCK_RE.sub(replace_block, html)
    html = MEDIA_SELF_RE.sub(replace_block, html)
    return html, media_items


def extract_page_media(raw_html: str, article_url: str) -> list[dict[str, Any]]:
    media_items: list[dict[str, Any]] = []
    for pattern in (MEDIA_CONTAINER_BLOCK_RE, MEDIA_EXPLICIT_BLOCK_RE, MEDIA_SELF_RE):
        for match in pattern.finditer(raw_html):
            media = build_media_item(
                match.group("tag"),
                match.group("attrs"),
                match.groupdict().get("body") or "",
                article_url=article_url,
                position="page",
            )
            if media:
                add_unique_media(media_items, media)
            if len(media_items) >= 12:
                return media_items

    marker_re = re.compile(
        r"songname|musicid|albumurl|qqmusic|mpvoice|mpaudio|mpvideo|video_iframe",
        flags=re.IGNORECASE,
    )
    for match in marker_re.finditer(raw_html):
        start = max(0, match.start() - 1600)
        end = min(len(raw_html), match.end() + 3000)
        media = build_media_item(
            "script",
            "",
            raw_html[start:end],
            article_url=article_url,
            position="page",
        )
        if media:
            add_unique_media(media_items, media)
        if len(media_items) >= 12:
            break
    return media_items


def clean_article_html_with_media(
    content_html: str,
    *,
    raw_html: str | None,
    article_url: str,
) -> CleanArticleResult:
    html, media_items = replace_media_elements(content_html, article_url)
    if raw_html:
        page_media = []
        for media in extract_page_media(raw_html, article_url):
            if all(media_signature(media) != media_signature(item) for item in media_items):
                page_media.append(media)
        if page_media:
            html = "".join(render_media_card(media, article_url) for media in page_media) + html
            media_items = page_media + media_items

    html = normalize_image_sources(html)
    html = re.sub(r"\sstyle=(['\"]).*?\1", "", html, flags=re.IGNORECASE | re.DOTALL)
    html = re.sub(r"\son[a-z]+=(['\"]).*?\1", "", html, flags=re.IGNORECASE | re.DOTALL)
    return {"html": html.strip(), "media": media_items}


def clean_article_html(content_html: str) -> str:
    return clean_article_html_with_media(content_html, raw_html=None, article_url="")["html"]


def manifest_media(media_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for item in media_items:
        clean_item = {key: value for key, value in item.items() if value not in (None, "", {})}
        result.append(clean_item)
    return result




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

        clean_result = clean_article_html_with_media(
            content_html,
            raw_html=raw_html,
            article_url=article.original_url,
        )
        clean_html = clean_result["html"]
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
            "media": manifest_media(clean_result["media"]),
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
