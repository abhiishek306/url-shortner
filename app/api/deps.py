from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer

from app.core.security import get_user_id_from_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")


async def get_current_user_id(token: str = Depends(oauth2_scheme)) -> int:
    return get_user_id_from_token(token)
