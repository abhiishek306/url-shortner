# Asynchronous High-Concurrency URL Shortener System Design

## 0. Objectives
- Build a low-latency URL shortening service with high read throughput.
- Support real-time analytics dashboards per user through WebSockets.
- Enforce abuse control through an atomic Redis-backed sliding-window rate limiter.
- Ensure click analytics durability with Redis Streams queueing and worker consumption.
- Keep all hot-path operations asynchronous and non-blocking.

## 1. Architecture Overview

### 1.1 Technology Stack
- FastAPI (ASGI app layer)
- PostgreSQL (source of truth for users, URLs, click analytics)
- Redis (cache + sliding-window limiter + pub/sub fan-out)
- Uvicorn/Gunicorn+Uvicorn workers (concurrency runtime)

### 1.2 Request Flow
1. Client calls `POST /api/v1/urls` with `x-user-id` and original URL.
2. FastAPI inserts row in PostgreSQL, gets numeric ID, encodes Base62 short ID.
3. Service caches `{url_id, user_id, original_url}` in Redis.
4. Client obtains JWT access token and opens `GET /ws/analytics/{user_id}?token=...`.
5. Browser/user clicks short URL `GET /{short_id}`.
6. Redirect handler does cache-first lookup.
7. Handler returns 302 immediately.
8. Redirect handler appends click event to Redis Stream `analytics:clicks`.
9. Worker consumes stream event, writes click analytics to PostgreSQL, and publishes JSON event to Redis channel `analytics:user:{user_id}`.
10. WebSocket handler subscribed to the channel pushes event to connected clients instantly.

### 1.3 Performance-Critical Path
- Redirect route avoids DB read when Redis cache hit occurs.
- Analytics persistence is decoupled through durable stream ingestion so redirect stays fast and restart-safe.
- Rate limiting runs as one atomic Lua script in Redis (single round trip, no race window).

## 2. Component Deep Dives

### 2.A Core Shortening Logic & Database

#### 2.A.1 Base62 Strategy
Numeric DB IDs are transformed into compact URL-safe strings using Base62 alphabet:
- Alphabet: `0-9a-zA-Z`
- Mapping: repeatedly divide by 62 and map remainder to alphabet index.
- Deterministic and collision-free when sourced from unique integer IDs.

Implementation: `app/core/base62.py`

URL creation first lets PostgreSQL allocate the URL sequence ID, then replaces a unique temporary insert value with the Base62 representation of that ID. A unique index on `short_id` remains the final collision guard.

#### 2.A.2 Data Model (SQLAlchemy)
Tables:
- `users`: owner entity
- `urls`: mapping of `short_id -> original_url`
- `click_analytics`: append-only click telemetry

Indexes optimized for hot operations:
- Unique index on `urls.short_id` for O(log n) redirect lookup.
- Compound indexes on analytics timeline queries (`url_id, clicked_at` and `user_id, clicked_at`).

Implementation: `app/db/models.py`

#### 2.A.3 Redirect Endpoint with Redis First
Redirect behavior:
1. Check Redis key `url:{short_id}`.
2. On hit, parse cached payload and redirect.
3. On miss, query PostgreSQL by indexed `short_id`, rehydrate cache, redirect.
4. Trigger async analytics task.

On a miss, the request acquires `url-lock:{short_id}` using Redis `SET NX EX`, then checks the cache again before accessing PostgreSQL. Other requests poll for the populated cache or acquire the lock after its owner exits; the owner renews its lease during a slow database lookup. Lock release compares the random ownership token, so a process cannot release a lock that has expired and been acquired by another process. Expired cache payloads are rejected as well as expired database rows.

Implementation: `app/api/routes.py` (`redirect_short_url`).

### 2.B Redis-Backed Sliding-Window Rate Limiter

#### 2.B.1 Algorithm
Per IP address:
- Store timestamps in a Redis sorted set.
- Remove entries older than window (`ZREMRANGEBYSCORE`).
- Read active count (`ZCARD`).
- Reject if count exceeds limit.
- Add current request and set TTL if allowed.

All operations are inside one Lua script for atomicity and correctness under concurrency.

#### 2.B.2 Exact Atomic Code Snippet
```python
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
```

Limiter wrapper and middleware:
- `app/services/rate_limiter.py`
- `app/middleware/rate_limiter.py`

Configured default: `20 requests / 60 seconds / IP`.

### 2.C Asynchronous WebSockets & Pub/Sub Pipeline

#### 2.C.1 Click Event Data Flow
1. Redirect endpoint calls `enqueue_click_event(...)`.
2. Function enqueues event payload into Redis Stream `analytics:clicks` with `XADD`.
3. Worker loop reads events via `XREADGROUP` and:
- Inserts row into `click_analytics` using the Stream ID as an idempotency key.
- Increments `urls.click_count` in the same PostgreSQL transaction, only when the analytics insert was new.
- Publishes event JSON to `analytics:user:{user_id}` Redis channel.
4. Worker periodically reclaims idle pending messages with `XAUTOCLAIM`. It acknowledges only after successful processing. Failed messages stay pending for retry and are written to `analytics:clicks:dead` after `REDIS_CLICK_MAX_ATTEMPTS`. Processing is at-least-once; database writes are idempotent, while a repeated Pub/Sub delivery is possible if acknowledgement fails after publication.
5. WebSocket endpoint subscribed to channel forwards each message to client.

Implementations:
- Publisher: `app/services/analytics_service.py`
- Subscriber socket: `app/ws/analytics_ws.py`

#### 2.C.2 WebSocket Endpoint
- Route: `/ws/analytics/{user_id}`
- Requires JWT token in query string and enforces `token.sub == {user_id}`.
- Uses Redis `pubsub()` object per connection.
- Polls asynchronously and pushes JSON updates immediately via `websocket.send_json(...)`.

## 3. Scalability & Concurrency

### 3.1 ASGI Concurrency Model for High Socket Counts
- FastAPI runs on asyncio event loop via Uvicorn.
- Each WebSocket connection is cooperative and non-blocking.
- Thousands of mostly-idle sockets are feasible because they consume memory, not one thread each.
- For multi-core scaling, run multiple worker processes (Gunicorn with Uvicorn workers).

Suggested launch pattern:
```bash
gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w 4 --bind 0.0.0.0:8000
```

Tuning notes:
- Increase file descriptor limits (`ulimit`/OS equivalent).
- Keep message payloads small.
- Use separate Redis instance or logical DB for Pub/Sub in heavy analytics workloads.

### 3.2 Redis Caching Strategy During Viral Spikes
Cache first redirect design protects PostgreSQL:
- A viral short link results in high repeated reads of same key.
- Redis serves those reads in-memory with low latency.
- DB only handles misses and write paths (URL creation, analytics logging).

Hardening recommendations:
- Add read-through cache warming for newly created URLs.
- Use jittered TTL to reduce synchronized expiry bursts.
- For extreme read patterns, add local in-process LRU on top of Redis for micro-hit acceleration.

### 3.3 Horizontal Scale
- API instances are stateless, safe to scale behind a load balancer.
- Redis provides shared coordination for cache, limiter state, and pub/sub messaging.
- PostgreSQL can scale with read replicas for analytics queries (writes remain on primary).
- Analytics workers run as separate processes/services and can be scaled independently from API pods.
- Nginx dynamically resolves the Compose `api` service and balances HTTP and WebSocket traffic. The stack starts two API replicas; increase with `docker compose up -d --scale api=N`.
- Database pool size and overflow are configurable per API worker process. Set these with replica count and PostgreSQL's maximum connection budget in mind.

### 3.4 Reproducible Validation
- Run `pytest -q` after installing `requirements-dev.txt` to exercise concurrent cache-miss coalescing and Stream retry/dead-letter behavior.
- `scripts/benchmark.py` runs a fixed request count at fixed concurrency and reports throughput plus p50/p95/p99/mean latency as JSON. Record the commit and environment, including machine resources, replica count, request count, concurrency, and warmup, when comparing results.

## 4. Reliability & Operations

### 4.1 Failure Modes
- Redis outage:
- Redirect can fall back to PostgreSQL reads.
- Rate limiter should fail closed or fail open based on policy (currently fail-open can be added).
- WebSocket real-time stream pauses until Redis returns.

- PostgreSQL outage:
- URL creation and analytics persistence fail.
- Cached redirects continue for existing hot keys until TTL expiry.

### 4.2 Production Enhancements
- Alembic migrations are used for schema lifecycle (`alembic upgrade head`).
- Add auth (JWT/OAuth) to map socket/user ownership securely.
- Evolve worker from in-process stream consumer to dedicated worker deployment for independent autoscaling.
- Add structured logging, OpenTelemetry tracing, and Prometheus metrics.
- Add dead letter/retry policy for failed analytics publish/write.

## 5. API Summary
- `POST /api/v1/auth/token` -> issue bearer token (bootstrap demo endpoint).
- `POST /api/v1/urls` (auth via bearer JWT) -> create short link.
- `GET /{short_id}` -> cached redirect + async analytics dispatch.
- `GET /health` -> liveness check.
- `WS /ws/analytics/{user_id}?token=...` -> real-time click events for authenticated user links.

## 6. Security Notes
- Validate and normalize destination URLs.
- Add domain allow/deny lists to prevent malicious redirect abuse.
- Apply TLS in transit for API, PostgreSQL, and Redis.
- Enforce origin checks and token-based auth on WebSocket endpoint.
- Rate-limit socket connection attempts separately from HTTP requests.
