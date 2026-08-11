import asyncio
import uuid

from app.services.analytics_service import run_analytics_worker
from app.services.redis_client import create_redis_client


async def _run() -> None:
    redis_client = create_redis_client()
    consumer_name = f"worker-{uuid.uuid4().hex[:8]}"

    try:
        await run_analytics_worker(redis_client, consumer_name)
    finally:
        await redis_client.aclose()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
