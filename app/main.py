from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.api.routes import api_router, public_router
from app.core.config import get_settings
from app.db.session import engine
from app.middleware.rate_limiter import RateLimitMiddleware
from app.services.rate_limiter import SlidingWindowRateLimiter
from app.services.redis_client import create_redis_client
from app.ws.analytics_ws import router as analytics_ws_router

settings = get_settings()


@asynccontextmanager
async def lifespan(application: FastAPI):
    application.state.redis = create_redis_client()
    application.state.rate_limiter = SlidingWindowRateLimiter(
        redis_client=application.state.redis,
        limit=settings.rate_limit_requests,
        window_seconds=settings.rate_limit_window_seconds,
        key_prefix="rl",
    )

    yield

    await application.state.redis.aclose()
    await engine.dispose()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(RateLimitMiddleware)
app.include_router(api_router)
app.include_router(public_router)
app.include_router(analytics_ws_router)


@app.get("/", include_in_schema=False)
async def index_page() -> HTMLResponse:
    return HTMLResponse(
        """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8" />
            <meta name="viewport" content="width=device-width, initial-scale=1.0" />
            <title>URL Shortener</title>
            <style>
                :root {
                    --bg: #0f172a;
                    --panel: #111827;
                    --panel-alt: #1f2937;
                    --primary: #22c55e;
                    --primary-dark: #16a34a;
                    --text: #e5e7eb;
                    --muted: #9ca3af;
                    --border: rgba(255,255,255,0.08);
                    --danger: #f59e0b;
                }
                * { box-sizing: border-box; }
                body {
                    margin: 0;
                    font-family: Arial, sans-serif;
                    background: linear-gradient(135deg, #020817, var(--bg));
                    color: var(--text);
                    min-height: 100vh;
                    padding: 32px 20px;
                }
                .layout {
                    width: min(1100px, 100%);
                    margin: 0 auto;
                    display: grid;
                    grid-template-columns: 1.3fr 0.9fr;
                    gap: 24px;
                }
                .card {
                    background: rgba(17, 24, 39, 0.95);
                    border: 1px solid var(--border);
                    border-radius: 18px;
                    box-shadow: 0 20px 60px rgba(0,0,0,0.35);
                    padding: 32px;
                }
                h1 {
                    margin: 0 0 12px;
                    font-size: clamp(2rem, 3vw, 3rem);
                }
                p {
                    color: var(--muted);
                    margin: 0 0 16px;
                }
                .field {
                    display: flex;
                    gap: 12px;
                    margin-top: 18px;
                    flex-wrap: wrap;
                }
                input {
                    flex: 1;
                    min-width: 220px;
                    padding: 14px 16px;
                    border-radius: 12px;
                    border: 1px solid var(--border);
                    background: rgba(255,255,255,0.03);
                    color: var(--text);
                    font-size: 1rem;
                }
                button {
                    border: none;
                    background: var(--primary);
                    color: #052e16;
                    font-weight: 700;
                    padding: 14px 22px;
                    border-radius: 12px;
                    cursor: pointer;
                    transition: 0.2s ease;
                }
                button:hover { background: var(--primary-dark); }
                button:disabled {
                    opacity: 0.6;
                    cursor: not-allowed;
                }
                .result {
                    margin-top: 22px;
                    padding: 18px;
                    border-radius: 12px;
                    background: var(--panel-alt);
                    border: 1px solid var(--border);
                    display: none;
                }
                .result.visible { display: block; }
                .result-actions {
                    display: flex;
                    gap: 12px;
                    flex-wrap: wrap;
                    margin-top: 10px;
                }
                .secondary-btn {
                    background: rgba(255,255,255,0.08);
                    color: var(--text);
                    border: 1px solid var(--border);
                }
                .secondary-btn:hover { background: rgba(255,255,255,0.12); }
                a {
                    color: #86efac;
                    word-break: break-all;
                }
                .status {
                    color: #fcd34d;
                    margin-top: 12px;
                    min-height: 22px;
                }
                .stats-grid {
                    display: grid;
                    grid-template-columns: repeat(2, minmax(120px, 1fr));
                    gap: 12px;
                    margin-top: 16px;
                }
                .stat-box {
                    background: rgba(255,255,255,0.02);
                    border: 1px solid var(--border);
                    border-radius: 12px;
                    padding: 14px 12px;
                }
                .stat-value {
                    display: block;
                    font-size: 1.5rem;
                    font-weight: 700;
                    color: #86efac;
                }
                .stat-label {
                    display: block;
                    color: var(--muted);
                    margin-top: 4px;
                    font-size: 0.82rem;
                }
                .analytics-card {
                    display: flex;
                    flex-direction: column;
                    gap: 16px;
                }
                .analytics-header {
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    gap: 12px;
                }
                .live-dot {
                    width: 10px;
                    height: 10px;
                    border-radius: 999px;
                    background: #22c55e;
                    box-shadow: 0 0 12px rgba(34, 197, 94, 0.9);
                    display: inline-block;
                }
                .links-table-wrap {
                    margin-top: 22px;
                    overflow: auto;
                    border: 1px solid var(--border);
                    border-radius: 12px;
                }
                table {
                    width: 100%;
                    border-collapse: collapse;
                    background: rgba(255,255,255,0.02);
                }
                th, td {
                    padding: 10px 12px;
                    border-bottom: 1px solid var(--border);
                    text-align: left;
                    vertical-align: top;
                }
                th {
                    color: var(--muted);
                    font-size: 0.78rem;
                    text-transform: uppercase;
                    letter-spacing: 0.06em;
                }
                td a {
                    color: #86efac;
                }
                .delete-btn {
                    background: rgba(239, 68, 68, 0.12);
                    color: #fecaca;
                    border: 1px solid rgba(239,68,68,0.4);
                    padding: 8px 10px;
                    font-size: 0.8rem;
                }
                .delete-btn:hover { background: rgba(239,68,68,0.2); }
                .analytics-list {
                    list-style: none;
                    padding: 0;
                    margin: 0;
                    display: flex;
                    flex-direction: column;
                    gap: 10px;
                    max-height: 460px;
                    overflow: auto;
                }
                .analytics-item {
                    background: rgba(255,255,255,0.02);
                    border: 1px solid var(--border);
                    border-radius: 12px;
                    padding: 12px 14px;
                    color: var(--text);
                }
                .analytics-item strong {
                    color: #86efac;
                }
                .analytics-item small {
                    display: block;
                    color: var(--muted);
                    margin-top: 6px;
                }
                @media (max-width: 820px) {
                    .layout {
                        grid-template-columns: 1fr;
                    }
                }
            </style>
        </head>
        <body>
            <div class="layout">
                <div class="card">
                    <h1>Shorten a URL</h1>
                    <p>Paste a long URL and create a compact redirect.</p>

                    <div class="field">
                        <input id="longUrl" type="url" placeholder="https://example.com/very/long/path" />
                        <button id="submitBtn" type="button">Create short link</button>
                    </div>

                    <div id="status" class="status"></div>

                    <div id="result" class="result">
                        <strong>Short URL:</strong>
                        <p><a id="shortLink" href="#" target="_blank" rel="noreferrer"></a></p>
                        <p>Original: <span id="originalLink"></span></p>
                        <div class="result-actions">
                            <button id="copyBtn" class="secondary-btn" type="button">Copy link</button>
                            <button id="visitBtn" class="secondary-btn" type="button">Visit link</button>
                        </div>
                    </div>

                    <div class="links-table-wrap">
                        <table>
                            <thead>
                                <tr>
                                    <th>Short</th>
                                    <th>Original</th>
                                    <th>Clicks</th>
                                    <th>Delete</th>
                                </tr>
                            </thead>
                            <tbody id="linksTableBody">
                                <tr>
                                    <td colspan="2" style="color: var(--muted);">No links yet.</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>

                <div class="card analytics-card">
                    <div class="analytics-header">
                        <h2 style="margin:0; font-size:1.3rem;">Live analytics</h2>
                        <span class="live-dot" aria-label="live analytics"></span>
                    </div>

                    <div class="stats-grid">
                        <div class="stat-box">
                            <span id="clickCount" class="stat-value">0</span>
                            <span class="stat-label">Clicks</span>
                        </div>
                        <div class="stat-box">
                            <span id="uniqueVisitors" class="stat-value">0</span>
                            <span class="stat-label">Visitors</span>
                        </div>
                    </div>

                    <p style="margin:0;">Click events appear here as they happen.</p>
                    <ul id="analyticsList" class="analytics-list">
                        <li class="analytics-item"><strong>No clicks yet.</strong><small>Visit a short link to start streaming analytics.</small></li>
                    </ul>
                </div>
            </div>

            <script>
                const statusEl = document.getElementById('status');
                const resultEl = document.getElementById('result');
                const shortLinkEl = document.getElementById('shortLink');
                const originalLinkEl = document.getElementById('originalLink');
                const inputEl = document.getElementById('longUrl');
                const submitBtn = document.getElementById('submitBtn');
                const analyticsList = document.getElementById('analyticsList');
                const linksTableBody = document.getElementById('linksTableBody');
                const copyBtn = document.getElementById('copyBtn');
                const visitBtn = document.getElementById('visitBtn');
                const clickCountEl = document.getElementById('clickCount');
                const uniqueVisitorsEl = document.getElementById('uniqueVisitors');

                let currentToken = null;
                let analyticsSocket = null;
                let totalClicks = 0;
                let uniqueVisitors = new Set();
                let latestShortUrl = '';

                function renderLinksTable(links) {
                    linksTableBody.innerHTML = '';
                    if (!links.length) {
                        linksTableBody.innerHTML = '<tr><td colspan="4" style="color: var(--muted);">No links yet.</td></tr>';
                        return;
                    }

                    for (const link of links) {
                        const row = document.createElement('tr');
                        row.innerHTML = `
                            <td><a href="${link.short_url}" target="_blank" rel="noreferrer">${link.short_url}</a></td>
                            <td>${link.original_url}</td>
                            <td>${link.click_count || 0}</td>
                            <td><button class="delete-btn" type="button" data-id="${link.id}">Delete</button></td>
                        `;
                        linksTableBody.appendChild(row);
                    }

                    linksTableBody.querySelectorAll('.delete-btn').forEach((button) => {
                        button.addEventListener('click', async () => {
                            const urlId = button.dataset.id;
                            try {
                                const token = await getToken();
                                const response = await fetch(`/api/v1/urls/${urlId}`, {
                                    method: 'DELETE',
                                    headers: { 'Authorization': `Bearer ${token}` }
                                });
                                if (!response.ok) {
                                    throw new Error('Delete failed');
                                }
                                await refreshLinksTable();
                                statusEl.textContent = 'Link deleted.';
                            } catch {
                                statusEl.textContent = 'Delete failed.';
                            }
                        });
                    });
                }

                async function refreshLinksTable() {
                    try {
                        const token = await getToken();
                        const response = await fetch('/api/v1/urls', {
                            method: 'GET',
                            headers: { 'Authorization': `Bearer ${token}` }
                        });
                        if (!response.ok) {
                            return;
                        }
                        const links = await response.json();
                        renderLinksTable(links);
                    } catch {
                        // Ignore refresh failures and allow the app to continue.
                    }
                }

                function addAnalyticsEvent(event) {
                    const item = document.createElement('li');
                    item.className = 'analytics-item';
                    const timestamp = new Date(event.clicked_at).toLocaleString();
                    item.innerHTML = `
                        <strong>${event.short_id}</strong>
                        <div>Browser: ${event.browser}</div>
                        <div>IP: ${event.ip_address}</div>
                        <small>${timestamp}</small>
                    `;
                    analyticsList.prepend(item);

                    if (event.short_id) {
                        uniqueVisitors.add(event.ip_address);
                    }
                    totalClicks += 1;
                    clickCountEl.textContent = String(totalClicks);
                    uniqueVisitorsEl.textContent = String(uniqueVisitors.size);

                    while (analyticsList.children.length > 8) {
                        analyticsList.removeChild(analyticsList.lastChild);
                    }
                }

                function connectAnalyticsSocket(token) {
                    if (analyticsSocket) {
                        analyticsSocket.close();
                    }

                    const wsUrl = `ws://${window.location.host}/ws/analytics/1?token=${token}`;
                    analyticsSocket = new WebSocket(wsUrl);

                    analyticsSocket.onopen = () => {
                        statusEl.textContent = 'Listening for click events...';
                    };

                    analyticsSocket.onmessage = (event) => {
                        const payload = JSON.parse(event.data);
                        addAnalyticsEvent(payload);
                    };

                    analyticsSocket.onclose = () => {
                        if (currentToken) {
                            setTimeout(() => connectAnalyticsSocket(currentToken), 1000);
                        }
                    };
                }

                async function getToken() {
                    const body = new URLSearchParams({ username: '1', password: 'dummy' });
                    const response = await fetch('/api/v1/auth/token', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                        body: body.toString(),
                    });
                    if (!response.ok) {
                        throw new Error('Could not get demo token');
                    }
                    const data = await response.json();
                    currentToken = data.access_token;
                    return currentToken;
                }

                async function shorten() {
                    const originalUrl = inputEl.value.trim();
                    if (!originalUrl) {
                        statusEl.textContent = 'Please paste a URL first.';
                        return;
                    }

                    submitBtn.disabled = true;
                    statusEl.textContent = 'Creating short link...';
                    resultEl.classList.remove('visible');

                    try {
                        const token = await getToken();
                        connectAnalyticsSocket(token);

                        const response = await fetch('/api/v1/urls', {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                                'Authorization': `Bearer ${token}`
                            },
                            body: JSON.stringify({ original_url: originalUrl })
                        });

                        const data = await response.json();
                        if (!response.ok) {
                            throw new Error(data.detail || 'Failed to create short URL');
                        }

                        latestShortUrl = data.short_url;
                        shortLinkEl.href = latestShortUrl;
                        shortLinkEl.textContent = latestShortUrl;
                        originalLinkEl.textContent = data.original_url;
                        resultEl.classList.add('visible');
                        await refreshLinksTable();
                        statusEl.textContent = 'Short link created successfully.';
                    } catch (error) {
                        statusEl.textContent = error.message || 'Something went wrong.';
                    } finally {
                        submitBtn.disabled = false;
                    }
                }

                async function copyShortLink() {
                    if (!latestShortUrl) {
                        statusEl.textContent = 'Create a short link before copying.';
                        return;
                    }

                    try {
                        await navigator.clipboard.writeText(latestShortUrl);
                        statusEl.textContent = 'Short link copied.';
                    } catch {
                        statusEl.textContent = 'Copy failed. Please copy manually.';
                    }
                }

                function visitShortLink() {
                    if (!latestShortUrl) {
                        statusEl.textContent = 'Create a short link before visiting.';
                        return;
                    }
                    window.open(latestShortUrl, '_blank', 'noopener,noreferrer');
                }

                submitBtn.addEventListener('click', shorten);
                inputEl.addEventListener('keydown', (event) => {
                    if (event.key === 'Enter') shorten();
                });
                copyBtn.addEventListener('click', copyShortLink);
                visitBtn.addEventListener('click', visitShortLink);

                getToken()
                    .then((token) => {
                        connectAnalyticsSocket(token);
                        return refreshLinksTable();
                    })
                    .catch(() => {
                        statusEl.textContent = 'Authentication failed. Please refresh the page.';
                    });
            </script>
        </body>
        </html>
        """
    )


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": settings.app_name}
