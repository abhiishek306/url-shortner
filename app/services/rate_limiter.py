import math
import time
import uuid

from redis.asyncio import Redis


SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local request_id = ARGV[4]

redis.call('ZREMRANGEBYSCORE', key, 0, now - window_ms)
local current_count = redis.call('ZCARD', key)

if current_count >= limit then
    local ttl = redis.call('PTTL', key)
    if ttl < 0 then
        ttl = window_ms
    end
    return {0, current_count, ttl}
end

redis.call('ZADD', key, now, request_id)
redis.call('PEXPIRE', key, window_ms)
return {1, current_count + 1, window_ms}
"""


class SlidingWindowRateLimiter:
    def __init__(self, redis_client: Redis, limit: int, window_seconds: int, key_prefix: str = "rate"):
        self.redis = redis_client
        self.limit = limit
        self.window_ms = window_seconds * 1000
        self.key_prefix = key_prefix

    async def is_allowed(self, identifier: str) -> tuple[bool, int, int]:
        key = f"{self.key_prefix}:{identifier}"
        now_ms = int(time.time() * 1000)
        request_id = f"{now_ms}-{uuid.uuid4().hex}"

        allowed, used_count, ttl_ms = await self.redis.eval(
            SLIDING_WINDOW_LUA,
            1,
            key,
            str(now_ms),
            str(self.window_ms),
            str(self.limit),
            request_id,
        )
        remaining = max(self.limit - int(used_count), 0)
        retry_after = max(math.ceil(int(ttl_ms) / 1000), 1)
        return bool(int(allowed)), remaining, retry_after
