from datetime import datetime

from pydantic import BaseModel


class ClickEvent(BaseModel):
    url_id: int
    short_id: str
    user_id: int
    ip_address: str
    browser: str
    referrer: str | None
    clicked_at: datetime
