import asyncio
import time

import pytest

from app.services.rate_limiter import SlidingWindowRateLimiter


class AtomicRedis:
    def __init__(self) -> None:
        self.requests: dict[str, dict[str, int]] = {}
        self._lock = asyncio.Lock()

    async def eval(
        self,
        script: str,
        key_count: int,
        key: str,
        now_ms: str,
        window_ms: str,
        limit: str,
        request_id: str,
    ) -> list[int]:
        async with self._lock:
            now = int(now_ms)
            window = int(window_ms)
            limit_value = int(limit)
            active = self.requests.setdefault(key, {})
            active = {
                member: score
                for member, score in active.items()
                if score > now - window
            }
            self.requests[key] = active
            if len(active) >= limit_value:
                return [0, len(active), window]
            active[request_id] = now
            return [1, len(active), window]


@pytest.mark.asyncio
async def test_concurrent_requests_never_exceed_rate_limit() -> None:
    limit = 12
    limiter = SlidingWindowRateLimiter(AtomicRedis(), limit=limit, window_seconds=60)

    decisions = await asyncio.gather(
        *(limiter.is_allowed("client") for _ in range(100))
    )

    assert sum(allowed for allowed, _, _ in decisions) == limit
    assert all(remaining >= 0 for _, remaining, _ in decisions)
    assert all(retry_after >= 1 for _, _, retry_after in decisions)


@pytest.mark.asyncio
async def test_rate_limit_allows_requests_again_after_window(monkeypatch: pytest.MonkeyPatch) -> None:
    now = 100.0
    monkeypatch.setattr(time, "time", lambda: now)
    limiter = SlidingWindowRateLimiter(AtomicRedis(), limit=1, window_seconds=1)

    first = await limiter.is_allowed("client")
    second = await limiter.is_allowed("client")
    now += 2
    third = await limiter.is_allowed("client")

    assert first[0]
    assert not second[0]
    assert third[0]
