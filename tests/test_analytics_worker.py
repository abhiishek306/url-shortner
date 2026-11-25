from datetime import datetime, timezone

import pytest
from sqlalchemy.dialects.postgresql.dml import Insert
from sqlalchemy.sql.dml import Update

from app.schemas.analytics import ClickEvent
from app.services import analytics_service


class FakeRedis:
    def __init__(self) -> None:
        self.attempts: dict[str, int] = {}
        self.acknowledged: list[str] = []
        self.dead_letters: list[dict[str, str]] = []
        self.pending: list[tuple[str, dict[str, str]]] = []
        self.published: list[tuple[str, str]] = []

    async def hincrby(self, key: str, field: str, amount: int) -> int:
        self.attempts[field] = self.attempts.get(field, 0) + amount
        return self.attempts[field]

    async def xadd(self, stream: str, fields: dict[str, str]) -> str:
        self.dead_letters.append(fields)
        return "2-0"

    async def xack(self, stream: str, group: str, message_id: str) -> int:
        self.acknowledged.append(message_id)
        return 1

    async def hdel(self, key: str, field: str) -> int:
        self.attempts.pop(field, None)
        return 1

    async def xautoclaim(
        self,
        name: str,
        groupname: str,
        consumername: str,
        min_idle_time: int,
        start_id: str,
        count: int,
    ) -> tuple[str, list[tuple[str, dict[str, str]]], list[str]]:
        pending = self.pending[:count]
        self.pending = self.pending[count:]
        return "0-0", pending, []

    async def publish(self, channel: str, message: str) -> int:
        self.published.append((channel, message))
        return 1


@pytest.mark.asyncio
async def test_failed_events_are_retried_then_dead_lettered(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = FakeRedis()

    async def fail_processing(event: object, stream_id: str, redis_client: object) -> None:
        raise RuntimeError("temporary database failure")

    monkeypatch.setattr(analytics_service, "process_click_event", fail_processing)
    payload = {
        "payload": (
            '{"url_id":1,"short_id":"abc","user_id":2,"ip_address":"127.0.0.1",'
            '"browser":"test","referrer":null,"clicked_at":"2026-01-01T00:00:00Z"}'
        )
    }

    for _ in range(analytics_service.settings.redis_click_max_attempts):
        await analytics_service.process_stream_message(redis, "1-0", payload)

    assert len(redis.dead_letters) == 1
    assert redis.dead_letters[0]["source_id"] == "1-0"
    assert redis.acknowledged == ["1-0"]
    assert "1-0" not in redis.attempts


@pytest.mark.asyncio
async def test_successful_event_is_acknowledged(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = FakeRedis()
    processed: list[str] = []

    async def process(event: object, stream_id: str, redis_client: object) -> None:
        processed.append(stream_id)

    monkeypatch.setattr(analytics_service, "process_click_event", process)
    payload = {
        "payload": (
            '{"url_id":1,"short_id":"abc","user_id":2,"ip_address":"127.0.0.1",'
            '"browser":"test","referrer":null,"clicked_at":"2026-01-01T00:00:00Z"}'
        )
    }
    await analytics_service.process_stream_message(redis, "1-0", payload)

    assert processed == ["1-0"]
    assert redis.acknowledged == ["1-0"]
    assert not redis.dead_letters


@pytest.mark.asyncio
async def test_transient_failure_remains_pending_and_can_be_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = FakeRedis()
    calls = 0

    async def recover(event: object, stream_id: str, redis_client: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary failure")

    monkeypatch.setattr(analytics_service, "process_click_event", recover)
    payload = {
        "payload": (
            '{"url_id":1,"short_id":"abc","user_id":2,"ip_address":"127.0.0.1",'
            '"browser":"test","referrer":null,"clicked_at":"2026-01-01T00:00:00Z"}'
        )
    }

    await analytics_service.process_stream_message(redis, "1-0", payload)
    assert redis.acknowledged == []

    await analytics_service.process_stream_message(redis, "1-0", payload)
    assert calls == 2
    assert redis.acknowledged == ["1-0"]


@pytest.mark.asyncio
async def test_reclaimed_pending_event_is_processed_and_acknowledged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = FakeRedis()
    processed: list[str] = []

    async def process(event: object, stream_id: str, redis_client: object) -> None:
        processed.append(stream_id)

    monkeypatch.setattr(analytics_service, "process_click_event", process)
    redis.pending.append(
        (
            "7-0",
            {
                "payload": (
                    '{"url_id":1,"short_id":"abc","user_id":2,"ip_address":"127.0.0.1",'
                    '"browser":"test","referrer":null,"clicked_at":"2026-01-01T00:00:00Z"}'
                )
            },
        )
    )

    claimed = await analytics_service.reclaim_pending_events(redis, "restarted-worker")

    assert claimed == 1
    assert processed == ["7-0"]
    assert redis.acknowledged == ["7-0"]


@pytest.mark.asyncio
async def test_duplicate_stream_delivery_does_not_increment_click_count_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Result:
        def __init__(self, value: int | None) -> None:
            self.value = value

        def scalar_one_or_none(self) -> int | None:
            return self.value

    class Database:
        def __init__(self) -> None:
            self.insert_count = 0
            self.click_count_updates = 0

        async def __aenter__(self) -> "Database":
            return self

        async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

        async def execute(self, statement: object) -> Result:
            if isinstance(statement, Insert):
                self.insert_count += 1
                return Result(1 if self.insert_count == 1 else None)
            if isinstance(statement, Update):
                self.click_count_updates += 1
                return Result(None)
            raise AssertionError(f"Unexpected SQL statement: {statement}")

        async def commit(self) -> None:
            return None

    database = Database()
    monkeypatch.setattr(analytics_service, "AsyncSessionLocal", lambda: database)
    redis = FakeRedis()

    event = ClickEvent(
        url_id=1,
        short_id="abc",
        user_id=2,
        ip_address="127.0.0.1",
        browser="test",
        referrer=None,
        clicked_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    await analytics_service.process_click_event(event, "7-0", redis)
    await analytics_service.process_click_event(event, "7-0", redis)

    assert database.insert_count == 2
    assert database.click_count_updates == 1
