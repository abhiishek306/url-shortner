from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_id
from app.core.config import get_settings
from app.core.security import create_access_token
from app.db.models import URL, User
from app.db.session import get_db
from app.schemas.url import CreateShortURLRequest, RedirectCachePayload, ShortURLResponse
from app.services.analytics_service import enqueue_click_event
from app.services.url_service import create_short_url, get_url_by_short_id

settings = get_settings()
api_router = APIRouter(prefix="/api/v1", tags=["urls"])
public_router = APIRouter(tags=["redirect"])


@api_router.get("/urls", response_model=list[ShortURLResponse])
async def list_urls(
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    stmt = select(URL).where(URL.user_id == user_id).order_by(URL.created_at.desc()).limit(20)
    result = await db.execute(stmt)
    urls = result.scalars().all()

    return [
        ShortURLResponse(
            id=url.id,
            short_id=url.short_id,
            short_url=f"{settings.short_domain.rstrip('/')}/{url.short_id}",
            original_url=url.original_url,
            created_at=url.created_at,
            expires_at=url.expires_at,
            click_count=url.click_count,
        )
        for url in urls
    ]


@api_router.delete("/urls/{url_id}", status_code=204)
async def delete_url(
    url_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    url = await db.get(URL, url_id)
    if not url or url.user_id != user_id:
        raise HTTPException(status_code=404, detail="URL not found")

    await db.delete(url)
    await db.commit()
    return None


@api_router.post("/urls", response_model=ShortURLResponse, status_code=201)
async def create_url(
    payload: CreateShortURLRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    url = await create_short_url(db, user_id=user_id, original_url=str(payload.original_url), expires_at=payload.expires_at)

    cache_payload = RedirectCachePayload(
        url_id=url.id,
        user_id=url.user_id,
        original_url=url.original_url,
        expires_at=url.expires_at,
    )
    await request.app.state.redis.setex(
        f"url:{url.short_id}",
        settings.cache_ttl_seconds,
        cache_payload.model_dump_json(),
    )

    return ShortURLResponse(
        id=url.id,
        short_id=url.short_id,
        short_url=f"{settings.short_domain.rstrip('/')}/{url.short_id}",
        original_url=url.original_url,
        created_at=url.created_at,
        expires_at=url.expires_at,
        click_count=url.click_count,
    )


@api_router.post("/auth/token")
async def issue_token(form_data: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    # Replace this with real credential validation and identity provider integration.
    try:
        user_id = int(form_data.username)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="username must be a numeric user ID") from exc

    existing_user = await db.get(User, user_id)
    if existing_user is None:
        db.add(User(id=user_id, email=f"user{user_id}@example.invalid"))
        await db.commit()

    token = create_access_token(subject=user_id)
    return {"access_token": token, "token_type": "bearer"}


@public_router.get("/{short_id}", status_code=302)
async def redirect_short_url(short_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    redis_key = f"url:{short_id}"
    cached = await request.app.state.redis.get(redis_key)

    if cached:
        cached_data = RedirectCachePayload.model_validate_json(cached)
        original_url = cached_data.original_url
        url_id = cached_data.url_id
        user_id = cached_data.user_id
    else:
        url = await get_url_by_short_id(db, short_id)
        if not url:
            raise HTTPException(status_code=404, detail="Short URL not found")

        cache_payload = RedirectCachePayload(
            url_id=url.id,
            user_id=url.user_id,
            original_url=url.original_url,
            expires_at=url.expires_at,
        )
        await request.app.state.redis.setex(
            redis_key,
            settings.cache_ttl_seconds,
            cache_payload.model_dump_json(),
        )
        original_url = url.original_url
        url_id = url.id
        user_id = url.user_id

    await enqueue_click_event(
        short_id=short_id,
        url_id=url_id,
        user_id=user_id,
        request=request,
        redis_client=request.app.state.redis,
    )
    return RedirectResponse(url=original_url, status_code=302)
