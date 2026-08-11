import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.core.config import get_settings
from app.core.security import TokenPayloadError, get_user_id_from_token

settings = get_settings()
router = APIRouter()


@router.websocket("/ws/analytics/{user_id}")
async def analytics_ws(websocket: WebSocket, user_id: int):
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Missing token")
        return

    try:
        authenticated_user_id = get_user_id_from_token(token)
    except TokenPayloadError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid token")
        return

    if authenticated_user_id != user_id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Forbidden channel access")
        return

    await websocket.accept()

    channel = f"{settings.redis_pubsub_prefix}{user_id}"
    pubsub = websocket.app.state.redis.pubsub()
    await pubsub.subscribe(channel)

    try:
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message and message.get("type") == "message":
                payload = json.loads(message["data"])
                await websocket.send_json(payload)
            await asyncio.sleep(0.05)
    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.close()
