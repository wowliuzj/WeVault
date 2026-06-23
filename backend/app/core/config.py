from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
    )

    app_name: str = "WeVault"
    app_env: str = "local"
    api_v1_prefix: str = "/api/v1"
    backend_port: int = 5726
    database_url: str = "postgresql+asyncpg://wevault:wevault@localhost:5432/wevault"
    redis_url: str = "redis://localhost:6379/0"
    secret_key: str = Field(default="change-me", min_length=8)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7
    admin_email: str | None = None
    admin_password: str | None = None
    admin_display_name: str = "Administrator"
    cloudflare_turnstile_secret_key: str | None = None
    asset_storage_dir: str = "storage"
    export_file_ttl_days: int = 14
    export_cleanup_interval_seconds: int = 60 * 60 * 6
    worker_poll_interval_seconds: float = 2.0
    worker_concurrency: int = 1
    worker_queue: str = "all"
    auto_fetch_schedule_time: str = "03:00"
    auto_fetch_lookback_days: int = 2
    wechat_browser_headless: bool = True
    wechat_login_timeout_seconds: int = 300
    cors_origins: list[str] = [
        "http://localhost:5725",
        "http://127.0.0.1:5725",
        "http://localhost:5727",
        "http://127.0.0.1:5727",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
