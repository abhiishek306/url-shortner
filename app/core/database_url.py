from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def normalize_async_database_url(raw_url: str) -> tuple[str, dict[str, object]]:
    """Normalize Postgres URLs for SQLAlchemy asyncpg and extract connect_args.

    Render-style URLs often include `sslmode=require`, but asyncpg expects an
    `ssl` argument instead of `sslmode`.
    """
    url = raw_url.strip()

    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

    parsed = urlsplit(url)
    query_items = parse_qsl(parsed.query, keep_blank_values=True)

    connect_args: dict[str, object] = {}
    filtered_query: list[tuple[str, str]] = []

    for key, value in query_items:
        lowered = key.lower()
        lowered_value = value.lower()

        if lowered == "sslmode":
            connect_args["ssl"] = False if lowered_value in {"disable", "allow"} else "require"
            continue

        if lowered == "ssl":
            if lowered_value in {"1", "true", "yes", "require"}:
                connect_args["ssl"] = True
            elif lowered_value in {"0", "false", "no", "disable"}:
                connect_args["ssl"] = False
            else:
                connect_args["ssl"] = value
            continue

        filtered_query.append((key, value))

    normalized_url = urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(filtered_query, doseq=True),
            parsed.fragment,
        )
    )

    return normalized_url, connect_args
