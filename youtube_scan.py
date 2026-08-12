#!/usr/bin/env python3
"""
youtube_scan.py
---------------
Optional YouTube demand signal (YouTube Data API v3): matching videos +
view/like/comment totals per product.

Fits V2 as a *secondary* social/content signal (not primary demand). Search
volume + quality factors still dominate score_demand.py; YouTube only
contributes small youtube_volume / youtube_engagement weights when present.

SETUP (~5 min, self-serve API key — no OAuth):
  1. https://console.cloud.google.com/ → project → enable YouTube Data API v3
  2. Credentials → API key (restrict key to YouTube Data API v3)
  3. YOUTUBE_API_KEY=... in .env

USAGE:
  python3 youtube_scan.py --estimate   # keyword plan + quota ceiling
  python3 youtube_scan.py              # full product list
  python3 youtube_scan.py --smoke      # first product only
  SKIP_YOUTUBE=1 ./run_all.sh          # skip from pipeline

QUOTA (free default 10,000 units/day):
  search.list = 100 units/call; videos.list = 1 unit (up to 50 IDs).
  Default: up to 2 search queries per product + 1 videos.list → ~201 units
  per product. ~19 products ≈ ~3.8k units — fine for weekly runs.

Soft-fail: missing API key writes zero rows with notes and exits 0 so
run_all.sh can continue (empty YouTube redistributes out of demand score).
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from cache_utils import cache_get, cache_put, load_cache, save_cache

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

try:
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError:
    build = None  # type: ignore
    HttpError = Exception  # type: ignore

USER_AGENT_NOTE = "printshop-demand-scan/0.2 (+local research; youtube-data-v3)"
DEFAULT_LOOKBACK_DAYS = 180
DEFAULT_MAX_RESULTS = 15
DEFAULT_KEYWORDS_PER_PRODUCT = 2
DEFAULT_DELAY_S = 0.35
# search.list=100, videos.list=1
UNITS_SEARCH = 100
UNITS_VIDEOS = 1
CACHE_PATH = Path("cache/youtube_cache.json")
DEFAULT_CACHE_TTL_DAYS = 7

FIELDNAMES = [
    "product",
    "category",
    "youtube_matching_videos",
    "youtube_total_views",
    "youtube_total_likes",
    "youtube_total_comments",
    "youtube_example_links",
    "youtube_keywords_used",
    "youtube_notes",
]


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def yt_settings(cfg: dict) -> dict:
    y = cfg.get("youtube") or {}
    return {
        "enabled": y.get("enabled", True),
        "lookback_days": int(y.get("lookback_days") or DEFAULT_LOOKBACK_DAYS),
        "max_results": int(y.get("max_results") or DEFAULT_MAX_RESULTS),
        "keywords_per_product": int(
            y.get("keywords_per_product") or DEFAULT_KEYWORDS_PER_PRODUCT
        ),
        "cache_ttl_days": int(y.get("cache_ttl_days") or DEFAULT_CACHE_TTL_DAYS),
        "use_cache": bool(y.get("use_cache", True)),
    }


def product_youtube_keywords(product: dict, max_kw: int) -> list[str]:
    """
    Prefer youtube_keywords, else product keywords (tighter), then a single
    search_volume keyword if still empty. Cap for quota.
    """
    ordered: list[str] = []
    for key in ("youtube_keywords", "keywords", "search_volume_keywords"):
        for k in product.get(key) or []:
            s = str(k).strip()
            if s and s not in ordered:
                ordered.append(s)
            if len(ordered) >= max_kw:
                return ordered
    return ordered[:max_kw]


def empty_row(product_name: str, category: str = "", notes: str = "") -> dict:
    return {
        "product": product_name,
        "category": category,
        "youtube_matching_videos": 0,
        "youtube_total_views": 0,
        "youtube_total_likes": 0,
        "youtube_total_comments": 0,
        "youtube_example_links": "",
        "youtube_keywords_used": "",
        "youtube_notes": notes,
    }


def write_rows(rows: list[dict], out_path: str) -> None:
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDNAMES})


def get_youtube_client():
    if build is None:
        print(
            "ERROR: google-api-python-client not installed. "
            "Run: pip install -r requirements.txt"
        )
        sys.exit(1)
    api_key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not api_key:
        return None
    return build("youtube", "v3", developerKey=api_key, cache_discovery=False)


class YoutubeAuthError(Exception):
    """Present-but-invalid/revoked API key (or similar credential HTTP error)."""

    def __init__(self, status: int):
        self.status = status
        super().__init__(f"YouTube auth/credential error HTTP {status}")


def _http_status(err: BaseException) -> int | None:
    """Best-effort status from googleapiclient HttpError or similar."""
    resp = getattr(err, "resp", None)
    if resp is not None:
        try:
            st = int(getattr(resp, "status", 0) or 0)
            if st:
                return st
        except (TypeError, ValueError):
            pass
    for attr in ("status_code", "status"):
        raw = getattr(err, attr, None)
        if raw is None:
            continue
        try:
            st = int(raw)
            if st:
                return st
        except (TypeError, ValueError):
            pass
    return None


def _raise_if_auth_http_error(err: BaseException) -> None:
    """Abort on 400/401/403 so a bad key is not treated as per-keyword noise."""
    status = _http_status(err)
    if status in (400, 401, 403):
        raise YoutubeAuthError(status) from err


def search_video_ids(
    youtube,
    keyword: str,
    *,
    published_after: str,
    max_results: int,
) -> list[str]:
    try:
        resp = (
            youtube.search()
            .list(
                q=keyword,
                part="id",
                type="video",
                order="relevance",
                maxResults=max(1, min(50, max_results)),
                publishedAfter=published_after,
                relevanceLanguage="en",
            )
            .execute()
        )
    except HttpError as e:
        _raise_if_auth_http_error(e)
        raise
    ids = []
    for item in resp.get("items") or []:
        vid = (item.get("id") or {}).get("videoId")
        if vid:
            ids.append(vid)
    return ids


def fetch_stats(youtube, video_ids: list[str]) -> tuple[int, int, int]:
    if not video_ids:
        return 0, 0, 0
    views = likes = comments = 0
    # API allows up to 50 IDs per videos.list
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i : i + 50]
        try:
            resp = (
                youtube.videos()
                .list(part="statistics", id=",".join(batch))
                .execute()
            )
        except HttpError as e:
            _raise_if_auth_http_error(e)
            raise
        for item in resp.get("items") or []:
            stats = item.get("statistics") or {}
            views += int(stats.get("viewCount") or 0)
            likes += int(stats.get("likeCount") or 0)
            comments += int(stats.get("commentCount") or 0)
    return views, likes, comments


def estimate(cfg: dict) -> None:
    settings = yt_settings(cfg)
    products = list(cfg.get("products") or [])
    max_kw = settings["keywords_per_product"]
    n_search = 0
    for p in products:
        n_search += len(product_youtube_keywords(p, max_kw)) or 0
    n_products = len(products)
    # One videos.list per product that has at least one search
    units = n_search * UNITS_SEARCH + n_products * UNITS_VIDEOS
    print("YouTube scan estimate (cold cache, no reuse across keywords):")
    print(f"  products:              {n_products}")
    print(f"  search.list calls:     {n_search} × {UNITS_SEARCH} = {n_search * UNITS_SEARCH}")
    print(f"  videos.list calls:     {n_products} × {UNITS_VIDEOS} = {n_products * UNITS_VIDEOS}")
    print(f"  estimated units:       ~{units}  (daily free quota 10,000)")
    print(f"  lookback_days:         {settings['lookback_days']}")
    print(f"  max_results/search:    {settings['max_results']}")
    print(f"  keywords_per_product:  {max_kw}")
    print("  weekly cache:          hits reduce search.list cost further")


def scan(
    config_path: str,
    out_path: str,
    *,
    smoke: bool = False,
    delay_s: float = DEFAULT_DELAY_S,
) -> list[dict]:
    cfg = load_config(config_path)
    settings = yt_settings(cfg)
    products = list(cfg.get("products") or [])
    if not products:
        print("No products in config.")
        write_rows([], out_path)
        return []

    if smoke:
        products = products[:1]
        print(f"SMOKE mode: only {products[0].get('name')!r}")

    if not settings["enabled"]:
        rows = [
            empty_row(p["name"], p.get("category") or "", "skipped: youtube.enabled=false")
            for p in products
        ]
        write_rows(rows, out_path)
        print(f"YouTube disabled in config — wrote empty rows to {out_path}")
        return rows

    youtube = get_youtube_client()
    if youtube is None:
        rows = [
            empty_row(
                p["name"],
                p.get("category") or "",
                "skipped: no YOUTUBE_API_KEY (set in .env)",
            )
            for p in products
        ]
        write_rows(rows, out_path)
        print(
            "WARN: YOUTUBE_API_KEY not set — wrote zero YouTube signal rows "
            f"to {out_path} (scoring will redistribute weights)."
        )
        return rows

    lookback = max(1, settings["lookback_days"])
    published_after = (
        datetime.now(timezone.utc) - timedelta(days=lookback)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    max_results = settings["max_results"]
    max_kw = settings["keywords_per_product"]
    use_cache = settings["use_cache"]
    ttl = settings["cache_ttl_days"]
    cache = load_cache(CACHE_PATH) if use_cache else {}

    rows: list[dict] = []
    units_used = 0
    cache_hits = 0

    def _finish_after_auth_error(status: int, partial_row: dict | None = None) -> list[dict]:
        """Write partial/empty CSV and stop — same soft exit philosophy as missing key."""
        note = (
            f"aborted: invalid or revoked YOUTUBE_API_KEY (HTTP {status})"
        )
        print(
            f"Invalid or revoked YOUTUBE_API_KEY (HTTP {status}). "
            "Fix the key in .env or remove it to soft-skip."
        )
        if partial_row is not None:
            prev = (partial_row.get("youtube_notes") or "").strip()
            partial_row["youtube_notes"] = f"{prev}; {note}".strip("; ")
            # Replace if same product already appended, else append.
            replaced = False
            for i, r in enumerate(rows):
                if r.get("product") == partial_row.get("product"):
                    rows[i] = partial_row
                    replaced = True
                    break
            if not replaced:
                rows.append(partial_row)
        done = {r.get("product") for r in rows}
        for p in products:
            pname = p["name"]
            if pname not in done:
                rows.append(
                    empty_row(pname, p.get("category") or "", note)
                )
        if use_cache:
            save_cache(CACHE_PATH, cache)
        write_rows(rows, out_path)
        print(
            f"\nWrote {len(rows)} rows to {out_path}  "
            f"(auth abort after ~{units_used} API units, cache_hits={cache_hits})"
        )
        return rows

    for product in products:
        name = product["name"]
        cat = product.get("category") or ""
        kws = product_youtube_keywords(product, max_kw)
        row = empty_row(name, cat)
        if not kws:
            row["youtube_notes"] = "no keywords"
            rows.append(row)
            print(f"  skip (no keywords): {name}")
            continue

        all_ids: list[str] = []
        notes: list[str] = []
        for kw in kws:
            ckey = f"search|{kw}|{lookback}|{max_results}"
            cached = cache_get(cache, ckey, ttl) if use_cache else None
            if cached is not None:
                ids = list(cached.get("video_ids") or [])
                cache_hits += 1
            else:
                try:
                    ids = search_video_ids(
                        youtube,
                        kw,
                        published_after=published_after,
                        max_results=max_results,
                    )
                    units_used += UNITS_SEARCH
                    if use_cache:
                        cache_put(cache, ckey, {"video_ids": ids})
                except YoutubeAuthError as e:
                    row["youtube_keywords_used"] = " | ".join(kws)
                    return _finish_after_auth_error(e.status, partial_row=row)
                except HttpError as e:
                    st = _http_status(e)
                    notes.append(
                        f"search_fail:{kw}:{st if st is not None else '?'}"
                    )
                    print(f"  [warn] search failed for {name!r} kw={kw!r}: {e}")
                    ids = []
                except Exception as e:
                    notes.append(f"search_fail:{kw}")
                    print(f"  [warn] search failed for {name!r} kw={kw!r}: {e}")
                    ids = []
                time.sleep(delay_s)
            for vid in ids:
                if vid not in all_ids:
                    all_ids.append(vid)

        views = likes = comments = 0
        if all_ids:
            # Same ID subset for cache key and API fetch (must stay identical).
            ids_for_stats = all_ids[:50]
            skey = f"stats|{'|'.join(ids_for_stats)}"
            cached_stats = cache_get(cache, skey, ttl) if use_cache else None
            if cached_stats is not None:
                views = int(cached_stats.get("views") or 0)
                likes = int(cached_stats.get("likes") or 0)
                comments = int(cached_stats.get("comments") or 0)
                cache_hits += 1
            else:
                try:
                    views, likes, comments = fetch_stats(youtube, ids_for_stats)
                    units_used += UNITS_VIDEOS
                    if use_cache:
                        cache_put(
                            cache,
                            skey,
                            {
                                "views": views,
                                "likes": likes,
                                "comments": comments,
                            },
                        )
                except YoutubeAuthError as e:
                    row["youtube_matching_videos"] = len(all_ids)
                    row["youtube_keywords_used"] = " | ".join(kws)
                    row["youtube_notes"] = "; ".join(notes)
                    return _finish_after_auth_error(e.status, partial_row=row)
                except Exception as e:
                    notes.append("stats_fail")
                    print(f"  [warn] stats failed for {name!r}: {e}")
                time.sleep(delay_s)

        row["youtube_matching_videos"] = len(all_ids)
        row["youtube_total_views"] = views
        row["youtube_total_likes"] = likes
        row["youtube_total_comments"] = comments
        row["youtube_example_links"] = " | ".join(
            f"https://youtube.com/watch?v={v}" for v in all_ids[:3]
        )
        row["youtube_keywords_used"] = " | ".join(kws)
        row["youtube_notes"] = "; ".join(notes)
        rows.append(row)
        print(
            f"  scanned: {name} -> {len(all_ids)} videos, "
            f"{views:,} views (kws={len(kws)})"
        )

    if use_cache:
        save_cache(CACHE_PATH, cache)

    write_rows(rows, out_path)
    print(
        f"\nWrote {len(rows)} rows to {out_path}  "
        f"(~{units_used} API units this run, cache_hits={cache_hits})"
    )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description="YouTube Data API v3 demand signal for demand-monitor V2"
    )
    parser.add_argument("--config", default="config/products.yaml")
    parser.add_argument("--out", default="out/youtube_signal.csv")
    parser.add_argument(
        "--estimate",
        action="store_true",
        help="Print keyword plan and quota ceiling; no API calls",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Scan first product only (cheap live test)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY_S,
        help="Seconds between API calls (default %.2f)" % DEFAULT_DELAY_S,
    )
    args = parser.parse_args()

    cfg = load_config(args.config)
    if args.estimate:
        estimate(cfg)
        return

    scan(args.config, args.out, smoke=args.smoke, delay_s=args.delay)


if __name__ == "__main__":
    main()
