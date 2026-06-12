from __future__ import annotations

import base64
import re
import struct
import zipfile
from datetime import UTC, datetime
from html import escape, unescape
from html.parser import HTMLParser
from pathlib import Path
from uuid import UUID

from playwright.async_api import async_playwright
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.article import Article, ArticleContent
from app.models.enums import ExportFormat, TaskStatus
from app.models.export import ExportFile, ExportJob
from app.models.wechat import WechatSource

EXPORT_CONTENT_TYPES = {
    ExportFormat.PDF: "application/pdf",
    ExportFormat.DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ExportFormat.MARKDOWN: "text/markdown; charset=utf-8",
    ExportFormat.ZIP: "application/zip",
}
EXPORT_EXTENSIONS = {
    ExportFormat.PDF: ".pdf",
    ExportFormat.DOCX: ".docx",
    ExportFormat.MARKDOWN: ".md",
}
DOCX_IMAGE_CONTENT_TYPES = {
    ".gif": "image/gif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
ZIP_BUNDLE_FORMATS = {
    "pdf": ExportFormat.PDF,
    "docx": ExportFormat.DOCX,
    "markdown": ExportFormat.MARKDOWN,
}
DocxBlock = tuple[str, str | Path]


def slugify_filename(value: str, *, default: str = "export") -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|\r\n\t]+", " ", value).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return (cleaned or default)[:80]


def export_storage_dir(job: ExportJob) -> Path:
    path = Path(settings.asset_storage_dir) / "exports" / str(job.user_id) / str(job.id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def article_markdown(article: Article, content: ArticleContent, source: WechatSource) -> str:
    markdown = content.markdown or content.plain_text or ""
    published = article.publish_time.isoformat() if article.publish_time else ""
    parts = [
        f"# {article.title}",
        "",
        f"- 公众号：{source.name}",
        f"- 发布时间：{published or '未知'}",
        f"- 原文：{article.original_url}",
        "",
        markdown.strip(),
        "",
    ]
    return "\n".join(parts)


def article_plain_text(article: Article, content: ArticleContent, source: WechatSource) -> str:
    return (
        f"{article.title}\n"
        f"公众号：{source.name}\n"
        f"发布时间：{article.publish_time.isoformat() if article.publish_time else '未知'}\n"
        f"原文：{article.original_url}\n\n"
        f"{content.plain_text or content.markdown or ''}"
    )


def content_assets(content: ArticleContent) -> list[dict]:
    manifest = content.assets_manifest or {}
    assets = manifest.get("assets") if isinstance(manifest, dict) else None
    return assets if isinstance(assets, list) else []


def asset_file(asset: dict) -> Path | None:
    storage_path = asset.get("storage_path")
    if not isinstance(storage_path, str) or not storage_path:
        return None
    path = Path(settings.asset_storage_dir) / storage_path
    return path if path.exists() else None


def article_cover_file(article: Article) -> Path | None:
    if not article.cover_storage_path:
        return None
    path = Path(settings.asset_storage_dir) / article.cover_storage_path
    return path if path.exists() else None


def image_content_type(path: Path) -> str:
    return DOCX_IMAGE_CONTENT_TYPES.get(path.suffix.lower(), "image/jpeg")


def image_data_uri(path: Path) -> str | None:
    try:
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError:
        return None
    return f"data:{image_content_type(path)};base64,{encoded}"


def html_with_embedded_assets(content: ArticleContent) -> str:
    fallback_text = escape(content.plain_text or content.markdown or "")
    html = content.clean_html or f"<pre>{fallback_text}</pre>"
    for asset in content_assets(content):
        asset_url = asset.get("asset_url")
        path = asset_file(asset)
        if not isinstance(asset_url, str) or path is None:
            continue
        data_uri = image_data_uri(path)
        if data_uri:
            html = html.replace(asset_url, data_uri)
    return html


def export_html(rows: list[tuple[Article, ArticleContent, WechatSource]]) -> str:
    body = []
    for article, content, source in rows:
        published = article.publish_time.isoformat() if article.publish_time else "未知"
        cover = article_cover_file(article)
        cover_html = ""
        if cover is not None:
            cover_src = image_data_uri(cover)
            if cover_src:
                cover_html = f"<img class='cover' src='{escape(cover_src, quote=True)}'>"
        body.append(
            "<article>"
            f"<h1>{escape(article.title)}</h1>"
            f"<p class='meta'>公众号：{escape(source.name)}"
            f" · 发布时间：{escape(published)}"
            f" · <a href='{escape(article.original_url, quote=True)}'>原文</a></p>"
            f"{cover_html}"
            f"{html_with_embedded_assets(content)}"
            "</article>"
        )
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<style>"
        "body{font-family:-apple-system,BlinkMacSystemFont,'PingFang SC',"
        "'Microsoft YaHei',sans-serif;line-height:1.7;color:#111827;padding:32px;}"
        "article{break-after:page;margin:0 auto 40px;max-width:760px;}"
        "img{max-width:100%;height:auto;}.cover{display:block;margin:0 0 20px;"
        "border-radius:8px;}h1{font-size:26px}.meta{color:#667085;font-size:13px;"
        "border-bottom:1px solid #e5e7eb;padding-bottom:12px}"
        "pre{white-space:pre-wrap}</style>"
        "</head><body>"
        + "\n".join(body)
        + "</body></html>"
    )


def xml_escape(value: str) -> str:
    return escape(value, quote=False)


def word_paragraph(text: str) -> str:
    return (
        "<w:p><w:r><w:t xml:space=\"preserve\">"
        f"{xml_escape(text)}"
        "</w:t></w:r></w:p>"
    )


class DocxHtmlParser(HTMLParser):
    def __init__(self, asset_paths: dict[str, Path]) -> None:
        super().__init__(convert_charrefs=True)
        self.asset_paths = asset_paths
        self.blocks: list[DocxBlock] = []
        self.text_parts: list[str] = []

    def flush_text(self) -> None:
        text = unescape("".join(self.text_parts))
        text = re.sub(r"[ \t\r\f\v]+", " ", text)
        text = re.sub(r"\n\s*", "\n", text)
        self.text_parts = []
        for line in text.splitlines():
            cleaned = line.strip()
            if cleaned:
                self.blocks.append(("text", cleaned))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.lower()
        if normalized_tag == "br":
            self.text_parts.append("\n")
            return
        if normalized_tag == "img":
            self.flush_text()
            attr_map = {name.lower(): value for name, value in attrs if value}
            src = attr_map.get("src") or attr_map.get("data-src")
            if src and src in self.asset_paths:
                self.blocks.append(("image", self.asset_paths[src]))
            return
        if normalized_tag in {"p", "div", "section", "li", "blockquote", "h1", "h2", "h3"}:
            self.flush_text()

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"p", "div", "section", "li", "blockquote", "h1", "h2", "h3"}:
            self.flush_text()

    def handle_data(self, data: str) -> None:
        self.text_parts.append(data)

    def close(self) -> None:
        super().close()
        self.flush_text()


def docx_asset_paths(content: ArticleContent) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for asset in content_assets(content):
        asset_url = asset.get("asset_url")
        path = asset_file(asset)
        if not isinstance(asset_url, str) or path is None:
            continue
        paths[asset_url] = path
        paths[path.resolve().as_uri()] = path
        original_url = asset.get("original_url")
        if isinstance(original_url, str):
            paths[original_url] = path
    return paths


def docx_content_blocks(content: ArticleContent) -> list[DocxBlock]:
    html = content.clean_html
    if html:
        parser = DocxHtmlParser(docx_asset_paths(content))
        parser.feed(html)
        parser.close()
        if parser.blocks:
            return parser.blocks

    text = content.plain_text or content.markdown or ""
    return [("text", line.strip()) for line in text.splitlines() if line.strip()]


def image_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()[:65536]
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    if data.startswith(b"\xff\xd8"):
        index = 2
        while index + 9 < len(data):
            if data[index] != 0xFF:
                index += 1
                continue
            marker = data[index + 1]
            length = struct.unpack(">H", data[index + 2 : index + 4])[0]
            if marker in {0xC0, 0xC2}:
                height, width = struct.unpack(">HH", data[index + 5 : index + 9])
                return width, height
            index += 2 + length
    return 900, 520


def docx_image_xml(rid: str, image_id: int, name: str, path: Path) -> str:
    width, height = image_size(path)
    max_width = 5_600_000
    cx = min(max_width, max(1, width) * 9525)
    cy = max(1, int(cx * max(1, height) / max(1, width)))
    return (
        "<w:p><w:r><w:drawing><wp:inline distT=\"0\" distB=\"0\" distL=\"0\" distR=\"0\">"
        f"<wp:extent cx=\"{cx}\" cy=\"{cy}\"/>"
        f"<wp:docPr id=\"{image_id}\" name=\"{xml_escape(name)}\"/>"
        "<a:graphic xmlns:a=\"http://schemas.openxmlformats.org/drawingml/2006/main\">"
        "<a:graphicData uri=\"http://schemas.openxmlformats.org/drawingml/2006/picture\">"
        "<pic:pic xmlns:pic=\"http://schemas.openxmlformats.org/drawingml/2006/picture\">"
        f"<pic:nvPicPr><pic:cNvPr id=\"{image_id}\" name=\"image\"/>"
        "<pic:cNvPicPr/></pic:nvPicPr>"
        "<pic:blipFill>"
        f"<a:blip r:embed=\"{rid}\"/>"
        "<a:stretch><a:fillRect/></a:stretch></pic:blipFill>"
        "<pic:spPr><a:xfrm><a:off x=\"0\" y=\"0\"/>"
        f"<a:ext cx=\"{cx}\" cy=\"{cy}\"/>"
        "</a:xfrm><a:prstGeom prst=\"rect\"><a:avLst/></a:prstGeom></pic:spPr>"
        "</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>"
    )


def supported_docx_image(asset: dict) -> tuple[Path, str] | None:
    path = asset_file(asset)
    if path is None:
        return None
    extension = path.suffix.lower()
    if extension not in DOCX_IMAGE_CONTENT_TYPES:
        return None
    content_type = str(asset.get("content_type") or "")
    allowed_content_types = {*DOCX_IMAGE_CONTENT_TYPES.values(), "image/jpg"}
    if content_type and content_type not in allowed_content_types:
        return None
    return path, extension


def supported_docx_path(path: Path) -> tuple[Path, str] | None:
    extension = path.suffix.lower()
    if path.exists() and extension in DOCX_IMAGE_CONTENT_TYPES:
        return path, extension
    return None


def append_docx_image(
    paragraphs: list[str],
    relationships: list[str],
    media: list[tuple[Path, str, str]],
    image_extensions: set[str],
    path: Path,
    next_rid: int,
) -> int:
    image = supported_docx_path(path)
    if image is None:
        return next_rid

    image_path, extension = image
    media_name = f"image{next_rid}{extension}"
    rid = f"rId{next_rid}"
    image_extensions.add(extension.lstrip("."))
    relationships.append(
        f'<Relationship Id="{rid}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
        f'Target="media/{media_name}"/>'
    )
    media.append((image_path, f"word/media/{media_name}", extension))
    paragraphs.append(docx_image_xml(rid, next_rid, media_name, image_path))
    return next_rid + 1


def build_docx_parts(
    rows: list[tuple[Article, ArticleContent, WechatSource]],
) -> tuple[str, str, list[tuple[Path, str, str]], set[str]]:
    paragraphs: list[str] = []
    relationships: list[str] = []
    media: list[tuple[Path, str, str]] = []
    image_extensions: set[str] = set()
    next_rid = 1
    for article, content, source in rows:
        published = article.publish_time.isoformat() if article.publish_time else "未知"
        paragraphs.append(word_paragraph(article.title))
        paragraphs.append(word_paragraph(f"公众号：{source.name}"))
        paragraphs.append(word_paragraph(f"发布时间：{published}"))
        paragraphs.append(word_paragraph(f"原文：{article.original_url}"))
        paragraphs.append("<w:p/>")

        cover = article_cover_file(article)
        if cover is not None:
            next_rid = append_docx_image(
                paragraphs,
                relationships,
                media,
                image_extensions,
                cover,
                next_rid,
            )

        for block_type, value in docx_content_blocks(content):
            if block_type == "image" and isinstance(value, Path):
                next_rid = append_docx_image(
                    paragraphs,
                    relationships,
                    media,
                    image_extensions,
                    value,
                    next_rid,
                )
            elif isinstance(value, str):
                paragraphs.append(word_paragraph(value))
        paragraphs.append("<w:p><w:r><w:br w:type=\"page\"/></w:r></w:p>")
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">'
        "<w:body>"
        + "".join(paragraphs)
        + "<w:sectPr><w:pgSz w:w=\"11906\" w:h=\"16838\"/><w:pgMar "
        'w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr>'
        "</w:body></w:document>"
    )
    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(relationships)
        + "</Relationships>"
    )
    return document_xml, rels_xml, media, image_extensions


def write_docx(file_path: Path, rows: list[tuple[Article, ArticleContent, WechatSource]]) -> None:
    document_xml, rels_xml, media, image_extensions = build_docx_parts(rows)
    image_defaults = "".join(
        (
            f'<Default Extension="{extension}" '
            f'ContentType="{DOCX_IMAGE_CONTENT_TYPES["." + extension]}"/>'
        )
        for extension in sorted(image_extensions)
    )
    with zipfile.ZipFile(file_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" '
            'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            + image_defaults
            +
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>",
        )
        archive.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
            'officeDocument" '
            'Target="word/document.xml"/></Relationships>',
        )
        archive.writestr("word/_rels/document.xml.rels", rels_xml)
        archive.writestr("word/document.xml", document_xml)
        for path, archive_name, _ in media:
            archive.write(path, archive_name)


async def write_pdf(
    file_path: Path,
    rows: list[tuple[Article, ArticleContent, WechatSource]],
) -> None:
    html = export_html(rows)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=settings.wechat_browser_headless)
        try:
            page = await browser.new_page()
            await page.set_content(html, wait_until="load")
            await page.pdf(
                path=file_path.as_posix(),
                format="A4",
                print_background=True,
                margin={"top": "18mm", "right": "16mm", "bottom": "18mm", "left": "16mm"},
            )
        finally:
            await browser.close()


async def write_export_payload(
    format_value: ExportFormat,
    file_path: Path,
    rows: list[tuple[Article, ArticleContent, WechatSource]],
) -> None:
    if format_value == ExportFormat.PDF:
        await write_pdf(file_path, rows)
    elif format_value == ExportFormat.DOCX:
        write_docx(file_path, rows)
    elif format_value == ExportFormat.MARKDOWN:
        body = "\n\n---\n\n".join(
            article_markdown(article, content, source) for article, content, source in rows
        )
        file_path.write_text(body, encoding="utf-8")
    else:
        raise RuntimeError(f"不支持的导出格式：{format_value.value}")


async def load_export_articles(
    db: AsyncSession,
    job: ExportJob,
) -> list[tuple[Article, ArticleContent, WechatSource]]:
    ids = [UUID(str(article_id)) for article_id in job.article_ids]
    result = await db.execute(
        select(Article, ArticleContent, WechatSource)
        .join(ArticleContent, ArticleContent.article_id == Article.id)
        .join(WechatSource, Article.source_id == WechatSource.id)
        .where(
            Article.user_id == job.user_id,
            Article.id.in_(ids),
            Article.deleted_at.is_(None),
            WechatSource.deleted_at.is_(None),
        )
    )
    rows = list(result.all())
    if len(rows) != len(set(ids)):
        raise RuntimeError("部分文章不存在或尚未抓取正文。")

    by_id = {article.id: (article, content, source) for article, content, source in rows}
    return [by_id[article_id] for article_id in ids]


async def run_export_job(db: AsyncSession, job: ExportJob) -> ExportFile:
    rows = await load_export_articles(db, job)
    await db.execute(delete(ExportFile).where(ExportFile.export_job_id == job.id))
    storage_dir = export_storage_dir(job)
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    base_name = slugify_filename(job.name, default=f"wevault-export-{timestamp}")

    bundle_formats = []
    if job.format == ExportFormat.ZIP and isinstance(job.options, dict):
        raw_formats = job.options.get("formats")
        if isinstance(raw_formats, list):
            bundle_formats = [
                ZIP_BUNDLE_FORMATS[value]
                for value in raw_formats
                if isinstance(value, str) and value in ZIP_BUNDLE_FORMATS
            ]

    if bundle_formats:
        file_name = f"{base_name}.zip"
        file_path = storage_dir / file_name
        with zipfile.ZipFile(file_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            for format_value in bundle_formats:
                extension = EXPORT_EXTENSIONS[format_value]
                inner_name = f"{base_name}{extension}"
                inner_path = storage_dir / f"bundle-{format_value.value}{extension}"
                await write_export_payload(format_value, inner_path, rows)
                archive.write(inner_path, inner_name)
    elif job.format in EXPORT_EXTENSIONS:
        file_name = f"{base_name}{EXPORT_EXTENSIONS[job.format]}"
        file_path = storage_dir / file_name
        await write_export_payload(job.format, file_path, rows)
    else:
        file_name = f"{base_name}.zip"
        file_path = storage_dir / file_name
        with zipfile.ZipFile(file_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            for index, (article, content, source) in enumerate(rows, start=1):
                entry_name = f"{index:03d}-{slugify_filename(article.title, default='article')}.md"
                archive.writestr(entry_name, article_markdown(article, content, source))

    export_file = ExportFile(
        export_job_id=job.id,
        file_name=file_name,
        file_path=file_path.as_posix(),
        content_type=EXPORT_CONTENT_TYPES[job.format],
        size_bytes=file_path.stat().st_size,
    )
    db.add(export_file)
    job.status = TaskStatus.SUCCEEDED
    job.error_message = None
    job.finished_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(export_file)
    return export_file
