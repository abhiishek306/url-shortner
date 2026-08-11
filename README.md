# Async URL Shortener (FastAPI + PostgreSQL + Redis + WebSockets)

Production-oriented asynchronous URL shortener with:
- Base62 short ID generation
- Redis cache-first 302 redirects
- Atomic sliding-window IP rate limiting
- Durable Redis Streams analytics ingestion
- Real-time click analytics streaming over WebSockets

## Project Layout
- `app/main.py`: FastAPI app, lifespan startup/shutdown
- `app/db/models.py`: SQLAlchemy models (`User`, `URL`, `ClickAnalytics`)
- `app/api/routes.py`: create URL + redirect endpoints
- `app/services/rate_limiter.py`: atomic Redis Lua limiter
- `app/ws/analytics_ws.py`: live analytics WebSocket endpoint
- `docs/SYSTEM_DESIGN.md`: full design document

## Live Browser Dashboard
The project is available locally at:

```text
http://localhost:8000
```

From the homepage you can:
- paste a long URL and create a short link
- copy or open the generated short URL
- watch live analytics events stream in real time
- view recent links, click totals, and delete links

## Features Included
- URL shortening with Base62 encoded IDs
- Fast redirect handling with Redis cache-first lookup
- PostgreSQL-backed persistence for users, URLs, and analytics
- Redis Streams for durable click event ingestion
- Real-time analytics updates over WebSockets
- Rate limiting per IP with atomic Redis sliding-window logic
- Dockerized local stack with PostgreSQL, Redis, API, worker, and migrator services

## Quick Start
1. Copy env template:
```bash
cp .env.example .env
```
2. Build and start all services (PostgreSQL, Redis, migrator, API, worker):
```bash
docker compose up -d --build
```
3. Verify service state:
```bash
docker compose ps
```

Optional PowerShell helper (does preflight checks + startup):
```powershell
./scripts/start-stack.ps1
```

## Example Usage
Issue bearer token for user `1`:
```bash
curl -X POST "http://localhost:8000/api/v1/auth/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=1&password=dummy"
```

Create short URL:
```bash
curl -X POST "http://localhost:8000/api/v1/urls" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <access_token>" \
  -d '{"original_url":"https://example.com/long/path"}'
```

Open WebSocket stream:
```bash
ws://localhost:8000/ws/analytics/1?token=<access_token>
```

Visit returned short URL:
```bash
http://localhost:8000/<short_id>
```

## Rate Limiting
Default limit is `20 requests/minute/IP`, configurable via:
- `RATE_LIMIT_REQUESTS`
- `RATE_LIMIT_WINDOW_SECONDS`

## How the System Works
1. A user creates a short URL from the browser or API.
2. The application stores the original URL and generates a Base62 short ID.
3. Redis caches the redirect metadata for faster hot-path lookups.
4. When a short URL is visited, the app issues a 302 redirect immediately.
5. A click event is queued to Redis Streams for durable analytics processing.
6. A background worker writes analytics to PostgreSQL and broadcasts updates to connected WebSocket clients.
7. The browser dashboard listens for these updates and refreshes live stats.

## API Endpoint Reference
### Authentication
- `POST /api/v1/auth/token`  
  Issues a bearer token for a demo user.

### URL Management
- `POST /api/v1/urls`  
  Creates a short URL. Requires a valid bearer token.
- `GET /api/v1/urls`  
  Lists recent URLs for the authenticated user.
- `DELETE /api/v1/urls/{url_id}`  
  Deletes a URL record owned by the user.

### Redirect + Analytics
- `GET /{short_id}`  
  Redirects to the original URL and triggers click analytics asynchronously.
- `GET /health`  
  Returns API health status.
- `WS /ws/analytics/{user_id}?token=...`  
  Streams real-time click events for the authenticated user.

## Deployment Notes
### Local development
```bash
docker compose up -d --build
```
Then open:
```text
http://localhost:8000
```

### Production-minded recommendations
- run the API behind a reverse proxy such as Nginx or Traefik
- place PostgreSQL and Redis in managed services or dedicated hosts
- scale API workers independently from analytics workers
- configure environment variables for your real domain, secret keys, and rate limits
- add HTTPS, auth hardening, and log/metric collection before exposing the service publicly
- use a proper identity provider instead of the demo token endpoint for production authentication

## Notes
- Token endpoint is a bootstrap demo and should be replaced with your identity provider.
- Analytics writes are consumed from a Redis stream by a dedicated worker process and then broadcast over Pub/Sub.
- API and analytics worker use the same Docker image but run as separate services for independent scaling.
- Migrator runs `alembic upgrade head` and API/worker start only after migrations complete successfully.
