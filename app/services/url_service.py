import asyncio
import logging
from datetime import datetime, timezone
import uuid

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base62 import encode_base62
from app.core.config import get_settings
from app.db.models import URL
from app.schemas.url import RedirectCachePayload

settings = get_settings()
logger = logging.getLogger(__name__)


async def create_short_url(
    db: AsyncSession,
    user_id: int,
    original_url: str,
    expires_at: datetime | None = None,
) -> URL:
    url = URL(
        user_id=user_id,
        original_url=original_url,
        expires_at=expires_at,
        short_id=uuid.uuid4().hex[:16],
    )
    db.add(url)
    await db.flush()

    url.short_id = encode_base62(url.id)
    await db.flush()
    await db.commit()
    await db.refresh(url)
    return url


_RELEASE_LOCK_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""

_RENEW_LOCK_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('EXPIRE', KEYS[1], ARGV[2])
end
return 0
"""


async def _renew_cache_lock(redis_client: Redis, lock_key: str, lock_token: str) -> None:
    while True:
        await asyncio.sleep(settings.cache_lock_ttl_seconds / 3)
        try:
            renewed = await redis_client.eval(
                _RENEW_LOCK_SCRIPT,
                1,
                lock_key,
                lock_token,
                settings.cache_lock_ttl_seconds,
            )
        except RedisError:
            logger.warning("Unable to renew Redis cache lock %s", lock_key, exc_info=True)
            return
        if not renewed:
            return


async def _cached_payload(redis_client: Redis, key: str) -> RedirectCachePayload | None:
    try:
        cached = await redis_client.get(key)
    except RedisError:
        logger.warning("Redis cache read failed for %s; falling back to PostgreSQL", key, exc_info=True)
        return None

    if not cached:
        return None
    try:
        payload = RedirectCachePayload.model_validate_json(cached)
    except ValueError:
        logger.warning("Invalid redirect cache payload for %s; ignoring it", key)
        try:
            await redis_client.delete(key)
        except RedisError:
            logger.warning("Unable to remove invalid redirect cache entry %s", key, exc_info=True)
        return None

    if payload.expires_at and payload.expires_at <= datetime.now(timezone.utc):
        try:
            await redis_client.delete(key)
        except RedisError:
            logger.warning("Unable to remove expired redirect cache entry %s", key, exc_info=True)
        return None
    return payload


async def get_redirect_payload(
    db: AsyncSession,
    redis_client: Redis,
    short_id: str,
) -> tuple[RedirectCachePayload | None, bool]:
    cache_key = f"url:{short_id}"
    payload = await _cached_payload(redis_client, cache_key)
    if payload:
        return payload, True

    lock_key = f"url-lock:{short_id}"
    lock_token = uuid.uuid4().hex
    lock_acquired = False
    renewal_task: asyncio.Task[None] | None = None

    try:
        while True:
            try:
                lock_acquired = bool(
                    await redis_client.set(
                        lock_key,
                        lock_token,
                        ex=settings.cache_lock_ttl_seconds,
                        nx=True,
                    )
                )
            except RedisError:
                logger.warning("Redis cache lock failed for %s; querying PostgreSQL", cache_key, exc_info=True)
                break

            if lock_acquired:
                renewal_task = asyncio.create_task(
                    _renew_cache_lock(redis_client, lock_key, lock_token)
                )
                payload = await _cached_payload(redis_client, cache_key)
                if payload:
                    return payload, True
                break

            payload = await _cached_payload(redis_client, cache_key)
            if payload:
                return payload, True
            await asyncio.sleep(0.05)

        url = await get_url_by_short_id(db, short_id)
        if not url:
            return None, False

        payload = RedirectCachePayload(
            url_id=url.id,
            user_id=url.user_id,
            original_url=url.original_url,
            expires_at=url.expires_at,
        )
        try:
            await redis_client.setex(
                cache_key,
                settings.cache_ttl_seconds,
                payload.model_dump_json(),
            )
        except RedisError:
            logger.warning("Redis cache write failed for %s", cache_key, exc_info=True)
        return payload, False
    finally:
        if lock_acquired:
            if renewal_task:
                renewal_task.cancel()
                await asyncio.gather(renewal_task, return_exceptions=True)
            try:
                await redis_client.eval(_RELEASE_LOCK_SCRIPT, 1, lock_key, lock_token)
            except RedisError:
                logger.warning("Unable to release Redis cache lock for %s", cache_key, exc_info=True)


async def get_url_by_short_id(db: AsyncSession, short_id: str) -> URL | None:
    stmt = select(URL).where(URL.short_id == short_id)
    result = await db.execute(stmt)
    url = result.scalar_one_or_none()
    if not url:
        return None

    if url.expires_at and url.expires_at <= datetime.now(timezone.utc):
        return None
    return url
