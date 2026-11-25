import asyncio
from types import SimpleNamespace

import pytest

from app.core.base62 import encode_base62
from app.schemas.url import RedirectCachePayload
from app.services import url_service


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.locks: dict[str, str] = {}
        self._guard = asyncio.Lock()

    async def get(self, key: str) -> str | None:
        return self.values.get(key) or self.locks.get(key)

    async def set(self, key: str, value: str, ex: int, nx: bool) -> bool:
        async with self._guard:
            if nx and key in self.locks:
                return False
            self.locks[key] = value
            return True

    async def setex(self, key: str, seconds: int, value: str) -> None:
        self.values[key] = value

    async def eval(self, script: str, key_count: int, key: str, token: str) -> int:
        if self.locks.get(key) == token:
            if "EXPIRE" in script:
                return 1
            del self.locks[key]
            return 1
        return 0

    async def delete(self, key: str) -> int:
        self.values.pop(key, None)
        return 1


@pytest.mark.asyncio
async def test_concurrent_cache_misses_are_coalesced(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = FakeRedis()
    db_calls = 0

    async def load_url(db: object, short_id: str) -> SimpleNamespace:
        nonlocal db_calls
        db_calls += 1
        await asyncio.sleep(0.05)
        return SimpleNamespace(
            id=17,
            user_id=3,
            original_url="https://example.com/",
            expires_at=None,
        )

    monkeypatch.setattr(url_service, "get_url_by_short_id", load_url)
    results = await asyncio.gather(
        *(url_service.get_redirect_payload(object(), redis, "abc123") for _ in range(20))
    )

    assert db_calls == 1
    assert all(isinstance(payload, RedirectCachePayload) for payload, _ in results)
    assert sum(not cache_hit for _, cache_hit in results) == 1


@pytest.mark.asyncio
async def test_cache_hit_skips_database_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = FakeRedis()
    cached_payload = RedirectCachePayload(
        url_id=17,
        user_id=3,
        original_url="https://example.com/",
    )
    redis.values["url:abc123"] = cached_payload.model_dump_json()

    async def fail_if_called(db: object, short_id: str) -> None:
        raise AssertionError("cache hit should not query PostgreSQL")

    monkeypatch.setattr(url_service, "get_url_by_short_id", fail_if_called)
    payload, cache_hit = await url_service.get_redirect_payload(object(), redis, "abc123")

    assert payload == cached_payload
    assert cache_hit


@pytest.mark.asyncio
async def test_concurrent_url_creation_uses_unique_sequence_ids() -> None:
    class Sequence:
        def __init__(self) -> None:
            self.value = 0

        def next(self) -> int:
            self.value += 1
            return self.value

    class FakeSession:
        def __init__(self, sequence: Sequence) -> None:
            self.sequence = sequence
            self.url = None

        def add(self, url: object) -> None:
            self.url = url

        async def flush(self) -> None:
            if self.url.id is None:
                self.url.id = self.sequence.next()

        async def commit(self) -> None:
            return None

        async def refresh(self, url: object) -> None:
            return None

    sequence = Sequence()

    async def create_one() -> object:
        return await url_service.create_short_url(
            FakeSession(sequence),
            user_id=5,
            original_url="https://example.com/",
        )

    created = await asyncio.gather(*(create_one() for _ in range(100)))
    short_ids = [url.short_id for url in created]

    assert len(set(short_ids)) == len(short_ids)
    assert all(url.short_id == encode_base62(url.id) for url in created)
