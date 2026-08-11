from datetime import datetime

from pydantic import AnyHttpUrl, BaseModel


class CreateShortURLRequest(BaseModel):
    original_url: AnyHttpUrl
    expires_at: datetime | None = None


class ShortURLResponse(BaseModel):
    id: int
    short_id: str
    short_url: str
    original_url: str
    created_at: datetime
    expires_at: datetime | None
    click_count: int = 0


class RedirectCachePayload(BaseModel):
    url_id: int
    user_id: int
    original_url: str
    expires_at: datetime | None = None
