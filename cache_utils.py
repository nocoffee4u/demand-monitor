"""
Shared weekly JSON cache helpers for demand-monitor scanners
(youtube_scan, ebay_sold_scan, etsy_scan, printables_cults_scan, …).

Behavior is intentionally simple and identical for all callers:
load/save whole dict, TTL via fetched_at ISO timestamp, opaque data blob.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def load_cache(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_cache(path: Path, cache: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2))


def cache_get(cache: dict, key: str, ttl_days: int) -> dict | None:
    entry = cache.get(key)
    if not entry:
        return None
    fetched = entry.get("fetched_at")
    if not fetched:
        return None
    try:
        ts = datetime.fromisoformat(fetched.replace("Z", "+00:00"))
    except ValueError:
        return None
    if datetime.now(timezone.utc) - ts > timedelta(days=ttl_days):
        return None
    data = entry.get("data")
    return data if isinstance(data, dict) else None


def cache_put(cache: dict, key: str, data: dict[str, Any]) -> None:
    cache[key] = {
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data": data,
    }


def clamp_limit(limit: int, *, lo: int = 1, hi: int = 50) -> int:
    """
    Clamp a page-size / result-limit so request params and cache keys match.
    Default hi=50 matches MakerWorld; callers may pass hi=100 (Etsy) etc.
    """
    try:
        n = int(limit)
    except (TypeError, ValueError):
        n = lo
    return max(lo, min(hi, n))
