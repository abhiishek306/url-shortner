from redis import asyncio as redis

from app.core.config import get_settings

settings = get_settings()


def create_redis_client() -> redis.Redis:
    return redis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
        health_check_interval=30,
    )
