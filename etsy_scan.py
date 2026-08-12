#!/usr/bin/env python3
"""
etsy_scan.py
------------
Optional Etsy marketplace demand signal via Etsy Open API v3
(application-level active listings search).

Fits V2 as a small *marketplace* signal for 3D-print buyers. Search volume +
quality factors still dominate score_demand.py; Etsy contributes small
etsy_engagement_volume (demand) and etsy_listing_saturation (competition)
weights when present.

IMPORTANT — what this can and cannot provide
  Official Etsy Open API v3 does **not** expose public sold/sales totals for
  arbitrary marketplace search. v1 uses:
    - etsy_listing_count  = active listings matching keywords (count)
    - etsy_avg_price      = mean listing price (USD)
    - etsy_favorites_proxy = sum of num_favorers on returned listings
    - etsy_sold_proxy     = 0 unless a future field appears; when 0, scoring
      falls back to favorites as an engagement proxy (documented in notes)
  This is still useful demand context (supply + interest), not transaction proof
  like eBay sold comps.

SETUP (~10 min, free developer app):
  1. https://www.etsy.com/developers/ → Register a new app
  2. Copy keystring + shared secret
  3. .env:
       ETSY_API_KEY=keystring:shared_secret
     (or ETSY_KEYSTRING=... and ETSY_SHARED_SECRET=...)

USAGE:
  python3 etsy_scan.py --estimate
  python3 etsy_scan.py
  python3 etsy_scan.py --smoke
  SKIP_ETSY=1 ./run_all.sh

QUOTA:
  Etsy rate-limits application keys (daily/minute caps vary by app tier).
  Default: up to 2 keyword searches per product × ~19 products ≈ 38 calls cold.
  Cache TTL 28 days (cache/etsy_cache.json) so weekly runs reuse results.

Soft-fail: missing key or API errors → zeros + notes, exit 0.
"""
from __future__ import annotations

import argparse
import csv
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
import yaml

from cache_utils import cache_get, cache_put, load_cache, save_cache

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

USER_AGENT = "printshop-demand-scan/0.2 (+local research; etsy-open-api-v3)"
API_BASE = "https://openapi.etsy.com/v3/application/listings/active"
DEFAULT_KEYWORDS_PER_PRODUCT = 2
DEFAULT_DELAY_S = 0.4
DEFAULT_CACHE_TTL_DAYS = 28
DEFAULT_LIMIT = 25  # listings per keyword page
CACHE_PATH = Path("cache/etsy_cache.json")

FIELDNAMES = [
    "product",
    "category",
    "etsy_listing_count",
    "etsy_sold_proxy",
    "etsy_avg_price",
    "etsy_favorites_proxy",
    "etsy_top_listing_title",
    "etsy_keywords_used",
    "etsy_notes",
    "fetched_at",
]


class EtsyAuthError(Exception):
    """Invalid/revoked API key (401/403)."""

    def __init__(self, status: int, detail: str = ""):
        self.status = status
        self.detail = detail
        super().__init__(f"Etsy API auth error HTTP {status}: {detail}")


class EtsyRateLimitError(Exception):
    """Rate limited (429) — fail-fast."""

    def __init__(self, retry_after: str = "", detail: str = ""):
        self.retry_after = retry_after or ""
        self.detail = detail
        super().__init__(
            "Etsy API rate limited (429)"
            + (f"; Retry-After={retry_after}" if retry_after else "")
        )


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def etsy_settings(cfg: dict) -> dict:
    e = cfg.get("etsy") or {}
    return {
        "enabled": e.get("enabled", True),
        "keywords_per_product": int(
            e.get("keywords_per_product") or DEFAULT_KEYWORDS_PER_PRODUCT
        ),
        "cache_ttl_days": int(e.get("cache_ttl_days") or DEFAULT_CACHE_TTL_DAYS),
        "use_cache": bool(e.get("use_cache", True)),
        "limit": int(e.get("limit") or DEFAULT_LIMIT),
    }


def product_etsy_keywords(product: dict, max_kw: int) -> list[str]:
    """etsy_keywords → keywords → search_volume_keywords (cap for quota)."""
    ordered: list[str] = []
    for key in ("etsy_keywords", "keywords", "search_volume_keywords"):
        for k in product.get(key) or []:
            s = str(k).strip()
            if s and s not in ordered:
                ordered.append(s)
            if len(ordered) >= max_kw:
                return ordered
    return ordered[:max_kw]


def empty_row(
    product_name: str,
    category: str = "",
    notes: str = "",
    fetched_at: str = "",
) -> dict:
    return {
        "product": product_name,
        "category": category,
        "etsy_listing_count": 0,
        "etsy_sold_proxy": 0,
        "etsy_avg_price": "",
        "etsy_favorites_proxy": 0,
        "etsy_top_listing_title": "",
        "etsy_keywords_used": "",
        "etsy_notes": notes,
        "fetched_at": fetched_at
        or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def write_rows(rows: list[dict], out_path: str) -> None:
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDNAMES})


def get_api_key() -> str | None:
    """
    x-api-key value: keystring:shared_secret
    Accept ETSY_API_KEY as full value, or ETSY_KEYSTRING + ETSY_SHARED_SECRET.
    """
    full = os.environ.get("ETSY_API_KEY", "").strip()
    if full:
        return full
    ks = os.environ.get("ETSY_KEYSTRING", "").strip()
    sec = os.environ.get("ETSY_SHARED_SECRET", "").strip()
    if ks and sec:
        return f"{ks}:{sec}"
    if ks:
        # Some apps allow keystring alone for limited public calls; still try
        return ks
    return None


def _listing_price_usd(listing: dict) -> float | None:
    price = listing.get("price") or {}
    if not isinstance(price, dict):
        return None
    try:
        amount = float(price.get("amount") or 0)
        divisor = float(price.get("divisor") or 100)
        if divisor <= 0:
            return None
        currency = (price.get("currency_code") or "USD").upper()
        usd = amount / divisor
        # Non-USD left as-is for v1 (most US sellers USD); no FX table
        if currency and currency != "USD":
            return usd  # still usable as relative band
        return usd
    except (TypeError, ValueError):
        return None


def fetch_active_listings(
    api_key: str,
    keywords: str,
    *,
    limit: int = DEFAULT_LIMIT,
    session: requests.Session | None = None,
) -> dict:
    """
    GET /v3/application/listings/active
    Auth: x-api-key: keystring:shared_secret
    """
    sess = session or requests.Session()
    params = {
        "keywords": keywords,
        "limit": clamp_limit(limit),
        "offset": 0,
        "sort_on": "score",
        "sort_order": "desc",
    }
    headers = {
        "x-api-key": api_key,
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    resp = sess.get(API_BASE, headers=headers, params=params, timeout=45)
    if resp.status_code in (401, 403):
        raise EtsyAuthError(resp.status_code, (resp.text or "")[:200])
    if resp.status_code == 429:
        raise EtsyRateLimitError(
            retry_after=str(resp.headers.get("Retry-After") or ""),
            detail=(resp.text or "")[:200],
        )
    if resp.status_code >= 400:
        raise RuntimeError(
            f"Etsy HTTP {resp.status_code}: {(resp.text or '')[:300]}"
        )
    return resp.json()


def clamp_limit(limit: int) -> int:
    """Same clamp applied to API request and cache keys."""
    return max(1, min(100, int(limit)))


def aggregate_listings(listings: list[dict], count_hint: int | None = None) -> dict:
    """Aggregate listing metrics from Open API active search results."""
    prices: list[float] = []
    favorites = 0
    top_title = ""
    top_fav = -1
    for li in listings:
        p = _listing_price_usd(li)
        if p is not None and p > 0:
            prices.append(p)
        fav = li.get("num_favorers")
        try:
            fav_i = int(fav or 0)
        except (TypeError, ValueError):
            fav_i = 0
        favorites += fav_i
        title = (li.get("title") or "").strip()
        if title and fav_i >= top_fav:
            top_fav = fav_i
            top_title = title[:200]

    # Official count if present (total matching), else sample size
    listing_count = count_hint if count_hint is not None else len(listings)
    try:
        listing_count = int(listing_count)
    except (TypeError, ValueError):
        listing_count = len(listings)

    avg_price: str | float = ""
    if prices:
        avg_price = round(float(statistics.mean(prices)), 2)

    return {
        "etsy_listing_count": listing_count,
        # True sold totals not available on public Open API search
        "etsy_sold_proxy": 0,
        "etsy_avg_price": avg_price,
        "etsy_favorites_proxy": favorites,
        "etsy_top_listing_title": top_title,
    }


def estimate(cfg: dict) -> None:
    settings = etsy_settings(cfg)
    products = list(cfg.get("products") or [])
    max_kw = settings["keywords_per_product"]
    n_kw = sum(len(product_etsy_keywords(p, max_kw)) for p in products)
    print("Etsy scan estimate (Open API v3 active listings, cold cache):")
    print(f"  products:                 {len(products)}")
    print(f"  keyword searches:         {n_kw}  (max {max_kw}/product)")
    print(f"  estimated API requests:   ~{n_kw} (cold cache only)")
    print(
        f"  cache TTL default:        {DEFAULT_CACHE_TTL_DAYS}d "
        f"(reuse across weekly runs)"
    )
    print(f"  limit per search:         {settings['limit']}")
    print("  Auth: x-api-key: $ETSY_API_KEY  (keystring:shared_secret)")
    print(f"  Endpoint: GET {API_BASE}?keywords=...")
    print(
        "  Note: etsy_sold_proxy stays 0 (no public sold counts); "
        "favorites + listing count still scored."
    )


def scan(
    config_path: str,
    out_path: str,
    *,
    smoke: bool = False,
    delay_s: float = DEFAULT_DELAY_S,
) -> list[dict]:
    cfg = load_config(config_path)
    settings = etsy_settings(cfg)
    products = list(cfg.get("products") or [])
    now = datetime.now(timezone.utc)
    fetched_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    if not products:
        print("No products in config.")
        write_rows([], out_path)
        return []

    if smoke:
        products = products[:1]
        print(f"SMOKE mode: only {products[0].get('name')!r}")

    if not settings["enabled"]:
        rows = [
            empty_row(
                p["name"],
                p.get("category") or "",
                "skipped: etsy.enabled=false",
                fetched_at,
            )
            for p in products
        ]
        write_rows(rows, out_path)
        print(f"Etsy disabled in config — wrote empty rows to {out_path}")
        return rows

    api_key = get_api_key()
    if not api_key:
        rows = [
            empty_row(
                p["name"],
                p.get("category") or "",
                "skipped: no ETSY_API_KEY (set keystring:shared_secret in .env)",
                fetched_at,
            )
            for p in products
        ]
        write_rows(rows, out_path)
        print(
            "WARN: ETSY_API_KEY not set — wrote zero Etsy signal rows "
            f"to {out_path} (scoring will redistribute weights)."
        )
        return rows

    max_kw = settings["keywords_per_product"]
    use_cache = settings["use_cache"]
    ttl = settings["cache_ttl_days"]
    limit = settings["limit"]
    cache = load_cache(CACHE_PATH) if use_cache else {}
    session = requests.Session()

    rows: list[dict] = []
    api_calls = 0
    cache_hits = 0

    def _finish_abort(
        *,
        note: str,
        message: str,
        detail: str = "",
        partial_row: dict | None = None,
    ) -> list[dict]:
        print(message)
        if detail:
            print(f"  detail: {detail[:200]}")
        if partial_row is not None:
            prev = (partial_row.get("etsy_notes") or "").strip()
            partial_row["etsy_notes"] = f"{prev}; {note}".strip("; ")
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
            if p["name"] not in done:
                rows.append(
                    empty_row(p["name"], p.get("category") or "", note, fetched_at)
                )
        if use_cache:
            save_cache(CACHE_PATH, cache)
        write_rows(rows, out_path)
        print(
            f"\nWrote {len(rows)} rows to {out_path}  "
            f"(abort after ~{api_calls} API calls, cache_hits={cache_hits})"
        )
        return rows

    for product in products:
        name = product["name"]
        cat = product.get("category") or ""
        kws = product_etsy_keywords(product, max_kw)
        row = empty_row(name, cat, fetched_at=fetched_at)
        if not kws:
            row["etsy_notes"] = "no keywords"
            rows.append(row)
            print(f"  skip (no keywords): {name}")
            continue

        all_listings: list[dict] = []
        count_hints: list[int] = []
        notes: list[str] = [
            "sold_proxy unavailable via Etsy Open API v3 (use favorites + listings)"
        ]
        req_limit = clamp_limit(limit)
        for kw in kws:
            # Cache key must use the same clamped limit as the HTTP request
            ckey = f"active|{kw}|{req_limit}"
            cached = cache_get(cache, ckey, ttl) if use_cache else None
            if cached is not None:
                listings = list(cached.get("listings") or [])
                count_hints.append(int(cached.get("count") or len(listings)))
                cache_hits += 1
            else:
                try:
                    payload = fetch_active_listings(
                        api_key, kw, limit=req_limit, session=session
                    )
                    api_calls += 1
                    listings = list(payload.get("results") or [])
                    count_val = payload.get("count")
                    try:
                        count_i = int(count_val) if count_val is not None else len(listings)
                    except (TypeError, ValueError):
                        count_i = len(listings)
                    count_hints.append(count_i)
                    if use_cache:
                        cache_put(
                            cache,
                            ckey,
                            {"listings": listings, "count": count_i},
                        )
                except EtsyAuthError as e:
                    row["etsy_keywords_used"] = " | ".join(kws)
                    row["etsy_notes"] = f"aborted: HTTP {e.status}"
                    return _finish_abort(
                        note=f"aborted: invalid ETSY_API_KEY (HTTP {e.status})",
                        message=(
                            f"Invalid or revoked ETSY_API_KEY (HTTP {e.status}). "
                            "Fix keystring:shared_secret in .env or remove to soft-skip."
                        ),
                        detail=e.detail,
                        partial_row=row,
                    )
                except EtsyRateLimitError as e:
                    row["etsy_keywords_used"] = " | ".join(kws)
                    row["etsy_notes"] = "aborted: HTTP 429"
                    ra = f" Retry-After={e.retry_after}." if e.retry_after else ""
                    return _finish_abort(
                        note="aborted: rate limited HTTP 429"
                        + (f" Retry-After={e.retry_after}" if e.retry_after else ""),
                        message=(
                            f"Etsy rate limited (HTTP 429).{ra} "
                            "Stopping remaining products to avoid burning quota."
                        ),
                        detail=e.detail,
                        partial_row=row,
                    )
                except Exception as e:
                    notes.append(f"search_fail:{kw}")
                    print(f"  [warn] Etsy search failed for {name!r} kw={kw!r}: {e}")
                    listings = []
                    count_hints.append(0)
                time.sleep(delay_s)

            # Dedupe by listing_id
            seen = {li.get("listing_id") for li in all_listings if li.get("listing_id")}
            for li in listings:
                lid = li.get("listing_id")
                if lid and lid in seen:
                    continue
                if lid:
                    seen.add(lid)
                all_listings.append(li)

        # Prefer max reported total count across keywords; else sample size
        count_hint = max(count_hints) if count_hints else len(all_listings)
        stats = aggregate_listings(all_listings, count_hint=count_hint)
        row.update(stats)
        row["etsy_keywords_used"] = " | ".join(kws)
        row["etsy_notes"] = "; ".join(notes)
        rows.append(row)
        print(
            f"  scanned: {name} -> listings={row['etsy_listing_count']} "
            f"fav={row['etsy_favorites_proxy']} "
            f"avg_price={row['etsy_avg_price'] or '—'} "
            f"sold_proxy={row['etsy_sold_proxy']}"
        )

    if use_cache:
        save_cache(CACHE_PATH, cache)

    write_rows(rows, out_path)
    print(
        f"\nWrote {len(rows)} rows to {out_path}  "
        f"(~{api_calls} API calls, cache_hits={cache_hits})"
    )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Etsy Open API v3 demand signal for demand-monitor V2"
    )
    parser.add_argument("--config", default="config/products.yaml")
    parser.add_argument("--out", default="out/etsy_signal.csv")
    parser.add_argument(
        "--estimate",
        action="store_true",
        help="Print keyword plan and request ceiling; no API calls",
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
