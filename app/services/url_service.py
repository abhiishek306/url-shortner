from datetime import datetime, timezone
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base62 import encode_base62
from app.db.models import URL


async def create_short_url(
    db: AsyncSession,
    user_id: int,
    original_url: str,
    expires_at: datetime | None = None,
) -> URL:
    temp_short_id = f"tmp-{uuid.uuid4().hex[:12]}"
    url = URL(
        user_id=user_id,
        original_url=original_url,
        expires_at=expires_at,
        short_id=temp_short_id,
    )
    db.add(url)
    await db.flush()

    url.short_id = encode_base62(url.id)
    await db.flush()
    await db.commit()
    await db.refresh(url)
    return url


async def get_url_by_short_id(db: AsyncSession, short_id: str) -> URL | None:
    stmt = select(URL).where(URL.short_id == short_id)
    result = await db.execute(stmt)
    url = result.scalar_one_or_none()
    if not url:
        return None

    if url.expires_at and url.expires_at < datetime.now(timezone.utc):
        return None
    return url
