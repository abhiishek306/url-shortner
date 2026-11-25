"""Run a fixed-request asynchronous redirect benchmark against one short URL."""

import argparse
import asyncio
import json
import math
import statistics
import time
from urllib.parse import urlsplit

import httpx
from redis.asyncio import Redis


def percentile(samples: list[float], percentile_value: float) -> float:
    ordered = sorted(samples)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * percentile_value) - 1))
    return ordered[index]


async def benchmark(
    url: str,
    concurrency: int,
    requests: int,
    warmup: int,
    cold_samples: int,
    redis_url: str,
) -> dict[str, object]:
    timeout = httpx.Timeout(10.0)
    latencies: list[float] = []
    cache_latencies: dict[str, list[float]] = {"HIT": [], "MISS": []}
    failures = 0
    warmup_failures = 0

    async with httpx.AsyncClient(follow_redirects=False, timeout=timeout) as client:
        for _ in range(warmup):
            try:
                response = await client.get(url)
                if response.status_code != 302:
                    warmup_failures += 1
            except httpx.HTTPError:
                warmup_failures += 1

        async def run_worker(worker_number: int) -> None:
            nonlocal failures
            for _ in range(worker_number, requests, concurrency):
                started = time.perf_counter()
                try:
                    response = await client.get(url)
                    latency_ms = (time.perf_counter() - started) * 1000
                    latencies.append(latency_ms)
                    cache_status = response.headers.get("x-url-cache", "").upper()
                    if cache_status in cache_latencies:
                        cache_latencies[cache_status].append(latency_ms)
                    if response.status_code != 302:
                        failures += 1
                except httpx.HTTPError:
                    latencies.append((time.perf_counter() - started) * 1000)
                    failures += 1

        started = time.perf_counter()
        await asyncio.gather(*(run_worker(worker) for worker in range(concurrency)))
        elapsed = time.perf_counter() - started

    hit_count = len(cache_latencies["HIT"])
    miss_count = len(cache_latencies["MISS"])
    classified_count = hit_count + miss_count
    hit_mean = statistics.fmean(cache_latencies["HIT"]) if hit_count else None
    miss_mean = statistics.fmean(cache_latencies["MISS"]) if miss_count else None
    cold_latencies: list[float] = []
    cold_failures = 0
    if cold_samples:
        short_id = urlsplit(url).path.strip("/").split("/")[-1]
        cache = Redis.from_url(redis_url, decode_responses=True)
        try:
            async with httpx.AsyncClient(follow_redirects=False, timeout=timeout) as client:
                for _ in range(cold_samples):
                    await cache.delete(f"url:{short_id}")
                    started = time.perf_counter()
                    try:
                        response = await client.get(url)
                        cold_latencies.append((time.perf_counter() - started) * 1000)
                        if response.status_code != 302 or response.headers.get("x-url-cache") != "MISS":
                            cold_failures += 1
                    except httpx.HTTPError:
                        cold_latencies.append((time.perf_counter() - started) * 1000)
                        cold_failures += 1
        finally:
            await cache.aclose()

    cold_mean = statistics.fmean(cold_latencies) if cold_latencies else None
    improvement = (
        round((cold_mean - hit_mean) / cold_mean * 100, 2)
        if hit_mean is not None and cold_mean is not None and cold_mean > 0
        else None
    )
    return {
        "url": url,
        "requests": requests,
        "concurrency": concurrency,
        "warmup_requests": warmup,
        "warmup_failures": warmup_failures,
        "elapsed_seconds": round(elapsed, 3),
        "throughput_requests_per_second": round(requests / elapsed, 2),
        "latency_ms": {
            "p50": round(percentile(latencies, 0.50), 2),
            "p95": round(percentile(latencies, 0.95), 2),
            "p99": round(percentile(latencies, 0.99), 2),
            "mean": round(statistics.fmean(latencies), 2),
        },
        "cache": {
            "hit_count": hit_count,
            "miss_count": miss_count,
            "unknown_count": requests - hit_count - miss_count,
            "hit_ratio": round(hit_count / classified_count, 4) if classified_count else None,
            "hit_mean_ms": round(hit_mean, 2) if hit_mean is not None else None,
            "miss_mean_ms": round(miss_mean, 2) if miss_mean is not None else None,
            "cold_sample_count": len(cold_latencies),
            "cold_mean_ms": round(cold_mean, 2) if cold_mean is not None else None,
            "cold_sample_failures": cold_failures,
            "hit_latency_improvement_percent": improvement,
        },
        "failures": failures,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Short URL to request, e.g. http://localhost:8000/abc")
    parser.add_argument("--concurrency", type=int, default=50)
    parser.add_argument("--requests", type=int, default=5000)
    parser.add_argument("--warmup", type=int, default=100)
    parser.add_argument(
        "--cold-samples",
        type=int,
        default=0,
        help="Sequentially clear the URL's Redis key and measure this many cold-cache requests",
    )
    parser.add_argument("--redis-url", default="redis://localhost:6379/0")
    args = parser.parse_args()
    if args.concurrency < 1 or args.requests < 1 or args.warmup < 0 or args.cold_samples < 0:
        parser.error("concurrency and requests must be positive; warmup and cold-samples cannot be negative")

    result = asyncio.run(
        benchmark(
            args.url,
            args.concurrency,
            args.requests,
            args.warmup,
            args.cold_samples,
            args.redis_url,
        )
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
