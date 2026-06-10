from enum import StrEnum


class UserStatus(StrEnum):
    ACTIVE = "active"
    RESTRICTED = "restricted"
    DISABLED = "disabled"


class TokenStatus(StrEnum):
    VALID = "valid"
    EXPIRED = "expired"
    INVALID = "invalid"
    UNKNOWN = "unknown"


class WechatLoginStatus(StrEnum):
    WAITING_SCAN = "waiting_scan"
    SCANNED = "scanned"
    CONFIRMED = "confirmed"
    EXPIRED = "expired"
    FAILED = "failed"


class SourceStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    FAILED = "failed"


class SourceFrom(StrEnum):
    SEARCH = "search"
    ARTICLE_URL = "article_url"
    MANUAL = "manual"


class FetchStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    FETCHED = "fetched"
    FAILED = "failed"


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskType(StrEnum):
    FETCH_SOURCE_ARTICLES = "fetch_source_articles"
    FETCH_ARTICLE_CONTENT = "fetch_article_content"
    FETCH_ARTICLE_COMMENTS = "fetch_article_comments"
    EXPORT_ARTICLES = "export_articles"


class ExportFormat(StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    MARKDOWN = "markdown"
    ZIP = "zip"
