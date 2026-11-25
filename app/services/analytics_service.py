import json
import logging
from datetime import datetime, timezone

from fastapi import Request
from redis.exceptions import ResponseError
from redis.asyncio import Redis
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from user_agents import parse

from app.core.config import get_settings
from app.db.models import ClickAnalytics, URL
from app.db.session import AsyncSessionLocal
from app.schemas.analytics import ClickEvent

settings = get_settings()
logger = logging.getLogger(__name__)


def _extract_browser(user_agent: str | None) -> str:
    if not user_agent:
        return "unknown"
    parsed = parse(user_agent)
    version = ".".join(str(v) for v in parsed.browser.version if v is not None)
    return f"{parsed.browser.family} {version}".strip()


async def enqueue_click_event(
    short_id: str,
    url_id: int,
    user_id: int,
    request: Request,
    redis_client: Redis,
) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    ip_address = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "unknown")

    event = ClickEvent(
        url_id=url_id,
        short_id=short_id,
        user_id=user_id,
        ip_address=ip_address,
        browser=_extract_browser(request.headers.get("user-agent")),
        referrer=request.headers.get("referer"),
        clicked_at=datetime.now(timezone.utc),
    )
    return await redis_client.xadd(
        settings.redis_click_stream,
        {
            "payload": event.model_dump_json(),
        },
    )


async def process_click_event(event: ClickEvent, stream_id: str, redis_client: Redis) -> None:
    async with AsyncSessionLocal() as db:
        statement = (
            insert(ClickAnalytics)
            .values(
                url_id=event.url_id,
                user_id=event.user_id,
                ip_address=event.ip_address,
                browser=event.browser,
                referrer=event.referrer,
                clicked_at=event.clicked_at,
                stream_id=stream_id,
            )
            .on_conflict_do_nothing(index_elements=[ClickAnalytics.stream_id])
            .returning(ClickAnalytics.id)
        )
        inserted_id = (await db.execute(statement)).scalar_one_or_none()
        if inserted_id is not None:
            stmt = update(URL).where(URL.id == event.url_id).values(click_count=URL.click_count + 1)
            await db.execute(stmt)
        await db.commit()

    channel = f"{settings.redis_pubsub_prefix}{event.user_id}"
    await redis_client.publish(channel, json.dumps(event.model_dump(mode="json")))


async def ensure_stream_group(redis_client: Redis) -> None:
    try:
        await redis_client.xgroup_create(
            name=settings.redis_click_stream,
            groupname=settings.redis_click_group,
            id="0",
            mkstream=True,
        )
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


async def process_stream_message(
    redis_client: Redis,
    message_id: str,
    fields: dict[str, str],
) -> None:
    attempts_key = f"{settings.redis_click_stream}:attempts"
    payload = fields.get("payload", "")
    try:
        if not payload:
            raise ValueError("Redis Stream message is missing its payload")
        event = ClickEvent.model_validate_json(payload)
        await process_click_event(event, message_id, redis_client)
    except Exception as exc:
        attempts = await redis_client.hincrby(attempts_key, message_id, 1)
        if attempts >= settings.redis_click_max_attempts:
            await redis_client.xadd(
                settings.redis_click_dead_letter_stream,
                {
                    "source_id": message_id,
                    "payload": payload,
                    "error": str(exc)[:1000],
                },
            )
            await redis_client.xack(
                settings.redis_click_stream,
                settings.redis_click_group,
                message_id,
            )
            await redis_client.hdel(attempts_key, message_id)
            logger.error("Moved analytics event %s to dead-letter stream", message_id, exc_info=True)
            return

        logger.warning(
            "Analytics event %s failed (attempt %s/%s); it remains pending for retry",
            message_id,
            attempts,
            settings.redis_click_max_attempts,
            exc_info=True,
        )
        return

    await redis_client.xack(
        settings.redis_click_stream,
        settings.redis_click_group,
        message_id,
    )
    await redis_client.hdel(attempts_key, message_id)


async def reclaim_pending_events(redis_client: Redis, consumer_name: str) -> int:
    claimed = await redis_client.xautoclaim(
        name=settings.redis_click_stream,
        groupname=settings.redis_click_group,
        consumername=consumer_name,
        min_idle_time=settings.redis_click_claim_idle_ms,
        start_id="0-0",
        count=100,
    )
    messages = claimed[1]
    for message_id, fields in messages:
        await process_stream_message(redis_client, message_id, fields)
    return len(messages)


async def run_analytics_worker(redis_client: Redis, consumer_name: str) -> None:
    await ensure_stream_group(redis_client)

    while True:
        await reclaim_pending_events(redis_client, consumer_name)

        stream_data = await redis_client.xreadgroup(
            groupname=settings.redis_click_group,
            consumername=consumer_name,
            streams={settings.redis_click_stream: ">"},
            count=100,
            block=5000,
        )
        if not stream_data:
            continue

        for _, messages in stream_data:
            for message_id, fields in messages:
                await process_stream_message(redis_client, message_id, fields)
