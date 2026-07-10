from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _to_asyncpg(url: str) -> str:
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://") and "+asyncpg" not in url:
        return "postgresql+asyncpg://" + url[len("postgresql://") :]
    return url


def _to_sync(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://") :]
    if "+asyncpg" in url:
        return url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Railway injects DATABASE_URL (postgres://...). Normalized in validator.
    database_url: str = (
        "postgresql+asyncpg://orderhunter:orderhunter@localhost:5433/orderhunter"
    )
    database_url_sync: str = (
        "postgresql://orderhunter:orderhunter@localhost:5433/orderhunter"
    )

    bot_token: str = ""
    admin_telegram_ids: str = ""

    internal_api_secret: str = "change-me"

    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-chat"
    llm_enabled: bool = True

    fl_ru_enabled: bool = False
    fl_ru_login: str = ""
    fl_ru_password: str = ""
    fl_ru_poll_interval_seconds: int = 300
    fl_ru_category_url: str = "https://www.fl.ru/projects/category/programmirovanie/"

    kwork_enabled: bool = False
    kwork_login: str = ""
    kwork_password: str = ""
    kwork_poll_interval_seconds: int = 300

    handler_leads_enabled: bool = False
    handler_leads_url: str = "http://localhost:3000/api/leads"

    worker_enabled: bool = True
    config_dir: str = "../config"
    port: int = 8000

    @model_validator(mode="after")
    def normalize_db_urls(self) -> "Settings":
        self.database_url = _to_asyncpg(self.database_url)
        default_sync = "postgresql://orderhunter:orderhunter@localhost:5433/orderhunter"
        if self.database_url_sync == default_sync:
            self.database_url_sync = _to_sync(self.database_url)
        else:
            self.database_url_sync = _to_sync(self.database_url_sync)
        return self

    @property
    def admin_id_list(self) -> list[int]:
        if not self.admin_telegram_ids.strip():
            return []
        return [int(x.strip()) for x in self.admin_telegram_ids.split(",") if x.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
