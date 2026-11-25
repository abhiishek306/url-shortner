from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Async URL Shortener"
    environment: str = "development"
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/url_shortener"
    redis_url: str = "redis://localhost:6379/0"
    short_domain: str = "http://localhost:8000"

    cache_ttl_seconds: int = 3600
    cache_lock_ttl_seconds: int = 5
    db_pool_size: int = 5
    db_max_overflow: int = 5
    rate_limit_requests: int = 20
    rate_limit_window_seconds: int = 60
    redis_pubsub_prefix: str = "analytics:user:"
    redis_click_stream: str = "analytics:clicks"
    redis_click_group: str = "analytics-workers"
    redis_click_dead_letter_stream: str = "analytics:clicks:dead"
    redis_click_max_attempts: int = 5
    redis_click_claim_idle_ms: int = 30000

    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
