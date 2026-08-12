#!/usr/bin/env python3
"""
ebay_sold_scan.py
-----------------
Optional eBay *sold/completed* listings demand signal via SoldComps
(https://sold-comps.com) — real sold prices and counts, not ask prices.

Fits V2 as a small *transaction* signal (not primary demand). Search volume +
quality factors still dominate score_demand.py; eBay only contributes small
ebay_sold_volume / ebay_price_signal weights when present.

SETUP (~5 min, self-serve API key — no OAuth):
  1. Create a free account at https://sold-comps.com (keys start with sc_)
  2. Dashboard → API keys
  3. EBAY_SOLD_API_KEY=sc_... in .env

USAGE:
  python3 ebay_sold_scan.py --estimate   # keyword plan + request ceiling
  python3 ebay_sold_scan.py              # full product list
  python3 ebay_sold_scan.py --smoke      # first product only
  SKIP_EBAY=1 ./run_all.sh               # skip from pipeline

QUOTA (SoldComps free tier often ~100 requests/month; paid plans higher):
  Default: up to 2 keyword searches per product (sold listings, 90d window)
  + 1 active-listings call per product for sell-through proxy.
  ~19 products × (2 sold + 1 active) ≈ ~57 requests when cold.
  Cache TTL defaults to 28 days (cache/ebay_sold_cache.json) so a weekly
  launchd run reuses results across ~4 weeks and stays under free-tier caps.

Soft-fail: missing API key or hard auth/quota/rate-limit errors write
zero/partial rows with notes and exit 0 so run_all.sh continues (empty eBay
redistributes).
"""
from __future__ import annotations

import argparse
import csv
import os
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
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

USER_AGENT = "printshop-demand-scan/0.2 (+local research; sold-comps ebay)"
API_BASE = "https://api.sold-comps.com/v1/scrape"
DEFAULT_KEYWORDS_PER_PRODUCT = 2
DEFAULT_DELAY_S = 0.6
# 28d TTL so weekly cadence reuses cache (~1 cold full run per month)
DEFAULT_CACHE_TTL_DAYS = 28
DEFAULT_COUNT = 120  # ceiling per request (API max 240)
CACHE_PATH = Path("cache/ebay_sold_cache.json")

FIELDNAMES = [
    "product",
    "category",
    "ebay_sold_count_30d",
    "ebay_sold_count_90d",
    "ebay_avg_sold_price",
    "ebay_median_sold_price",
    "ebay_min_sold_price",
    "ebay_max_sold_price",
    "ebay_sell_through_proxy",
    "ebay_top_title",
    "ebay_keywords_used",
    "ebay_notes",
    "fetched_at",
]


class EbayAuthError(Exception):
    """Invalid/revoked key or monthly quota exhausted (401/403)."""

    def __init__(self, status: int, detail: str = ""):
        self.status = status
        self.detail = detail
        super().__init__(f"eBay sold API auth/quota error HTTP {status}: {detail}")


class EbayRateLimitError(Exception):
    """Per-minute rate limit (HTTP 429) — fail-fast, do not burn more quota."""

    def __init__(self, retry_after: str = "", detail: str = ""):
        self.retry_after = retry_after or ""
        self.detail = detail
        super().__init__(
            f"eBay sold API rate limited (429)"
            + (f"; Retry-After={retry_after}" if retry_after else "")
        )


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def ebay_settings(cfg: dict) -> dict:
    e = cfg.get("ebay") or cfg.get("ebay_sold") or {}
    return {
        "enabled": e.get("enabled", True),
        "keywords_per_product": int(
            e.get("keywords_per_product") or DEFAULT_KEYWORDS_PER_PRODUCT
        ),
        "cache_ttl_days": int(e.get("cache_ttl_days") or DEFAULT_CACHE_TTL_DAYS),
        "use_cache": bool(e.get("use_cache", True)),
        "count": int(e.get("count") or DEFAULT_COUNT),
        "ebay_site": str(e.get("ebay_site") or "ebay.com"),
        "fetch_active_for_sell_through": bool(
            e.get("fetch_active_for_sell_through", True)
        ),
    }


def product_ebay_keywords(product: dict, max_kw: int) -> list[str]:
    """ebay_keywords → keywords → search_volume_keywords (cap for quota)."""
    ordered: list[str] = []
    for key in ("ebay_keywords", "keywords", "search_volume_keywords"):
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
        "ebay_sold_count_30d": 0,
        "ebay_sold_count_90d": 0,
        "ebay_avg_sold_price": "",
        "ebay_median_sold_price": "",
        "ebay_min_sold_price": "",
        "ebay_max_sold_price": "",
        "ebay_sell_through_proxy": 0,
        "ebay_top_title": "",
        "ebay_keywords_used": "",
        "ebay_notes": notes,
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
    key = os.environ.get("EBAY_SOLD_API_KEY", "").strip()
    return key or None


def _parse_price(raw: Any) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        return float(str(raw).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _parse_ended_at(raw: Any) -> datetime | None:
    if not raw:
        return None
    s = str(raw).strip()
    try:
        if "T" in s:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        # YYYY-MM-DD
        return datetime.strptime(s[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def fetch_soldcomps(
    api_key: str,
    keyword: str,
    *,
    sold: bool = True,
    sold_after: str | None = None,
    count: int = DEFAULT_COUNT,
    ebay_site: str = "ebay.com",
    page: int = 1,
    session: requests.Session | None = None,
) -> dict:
    """
    GET https://api.sold-comps.com/v1/scrape
    Auth: Authorization: Bearer sc_...
    """
    sess = session or requests.Session()
    params: dict[str, Any] = {
        "keyword": keyword,
        "page": page,
        "count": max(1, min(240, count)),
        "ebaySite": ebay_site,
        "sortOrder": "endedRecently",
        "sold": "true" if sold else "false",
    }
    if sold and sold_after:
        params["soldAfter"] = sold_after
    headers = {
        "Authorization": f"Bearer {api_key}",
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    resp = sess.get(API_BASE, headers=headers, params=params, timeout=60)
    if resp.status_code in (401, 403):
        raise EbayAuthError(
            resp.status_code,
            (resp.text or "")[:200],
        )
    if resp.status_code == 429:
        raise EbayRateLimitError(
            retry_after=str(resp.headers.get("Retry-After") or ""),
            detail=(resp.text or "")[:200],
        )
    if resp.status_code >= 400:
        raise RuntimeError(
            f"SoldComps HTTP {resp.status_code}: {(resp.text or '')[:300]}"
        )
    return resp.json()


def aggregate_sold_items(
    items: list[dict],
    *,
    now: datetime,
) -> dict[str, Any]:
    """Compute 30d/90d counts and price stats from SoldComps sold items."""
    cutoff_30 = now - timedelta(days=30)
    cutoff_90 = now - timedelta(days=90)
    count_30 = 0
    count_90 = 0
    clean_30: list[float] = []
    clean_90: list[float] = []
    titles_90: list[tuple[float, str]] = []

    for it in items:
        ended = _parse_ended_at(it.get("endedAt"))
        price = _parse_price(it.get("soldPrice"))
        title = (it.get("title") or "").strip()
        if ended is None:
            continue
        if ended.tzinfo is None:
            ended = ended.replace(tzinfo=timezone.utc)
        if ended < cutoff_90:
            continue
        count_90 += 1
        if price is not None:
            clean_90.append(price)
            if title:
                titles_90.append((price, title))
        if ended >= cutoff_30:
            count_30 += 1
            if price is not None:
                clean_30.append(price)

    # Prefer 30d prices for stats; fall back to 90d
    use_prices = clean_30 if clean_30 else clean_90
    top_title = ""
    if titles_90:
        titles_90.sort(key=lambda x: x[0], reverse=True)
        top_title = titles_90[0][1][:200]

    def _stat(fn, vals: list[float]) -> str | float:
        if not vals:
            return ""
        return round(float(fn(vals)), 2)

    return {
        "ebay_sold_count_30d": count_30,
        "ebay_sold_count_90d": count_90,
        "ebay_avg_sold_price": _stat(statistics.mean, use_prices),
        "ebay_median_sold_price": _stat(statistics.median, use_prices),
        "ebay_min_sold_price": _stat(min, use_prices),
        "ebay_max_sold_price": _stat(max, use_prices),
        "ebay_top_title": top_title,
    }


def estimate(cfg: dict) -> None:
    settings = ebay_settings(cfg)
    products = list(cfg.get("products") or [])
    max_kw = settings["keywords_per_product"]
    n_kw = sum(len(product_ebay_keywords(p, max_kw)) for p in products)
    n_prod = len(products)
    active = n_prod if settings["fetch_active_for_sell_through"] else 0
    total = n_kw + active
    print("eBay sold scan estimate (SoldComps, cold cache):")
    print(f"  products:                 {n_prod}")
    print(f"  sold keyword searches:    {n_kw}  (max {max_kw}/product)")
    print(f"  active sell-through:      {active}  (1/product if enabled)")
    print(f"  estimated API requests:   ~{total} (cold cache only)")
    print(
        f"  free tier note:           often ~100 req/month — "
        f"cache TTL default {DEFAULT_CACHE_TTL_DAYS}d (reuse across weekly runs)"
    )
    print(f"  ebay_site:                {settings['ebay_site']}")
    print(f"  count per request:        {settings['count']}")
    print("  Auth: Authorization: Bearer $EBAY_SOLD_API_KEY  (keys start with sc_)")
    print("  Endpoint: GET https://api.sold-comps.com/v1/scrape?keyword=...")


def scan(
    config_path: str,
    out_path: str,
    *,
    smoke: bool = False,
    delay_s: float = DEFAULT_DELAY_S,
) -> list[dict]:
    cfg = load_config(config_path)
    settings = ebay_settings(cfg)
    products = list(cfg.get("products") or [])
    now = datetime.now(timezone.utc)
    fetched_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    sold_after_90 = (now - timedelta(days=90)).strftime("%Y-%m-%d")

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
                "skipped: ebay.enabled=false",
                fetched_at,
            )
            for p in products
        ]
        write_rows(rows, out_path)
        print(f"eBay sold disabled in config — wrote empty rows to {out_path}")
        return rows

    api_key = get_api_key()
    if not api_key:
        rows = [
            empty_row(
                p["name"],
                p.get("category") or "",
                "skipped: no EBAY_SOLD_API_KEY (set in .env)",
                fetched_at,
            )
            for p in products
        ]
        write_rows(rows, out_path)
        print(
            "WARN: EBAY_SOLD_API_KEY not set — wrote zero eBay sold rows "
            f"to {out_path} (scoring will redistribute weights)."
        )
        return rows

    max_kw = settings["keywords_per_product"]
    use_cache = settings["use_cache"]
    ttl = settings["cache_ttl_days"]
    count = settings["count"]
    site = settings["ebay_site"]
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
        """Fail-fast: one message, fill remaining products, write CSV, exit soft."""
        print(message)
        if detail:
            print(f"  detail: {detail[:200]}")
        if partial_row is not None:
            prev = (partial_row.get("ebay_notes") or "").strip()
            partial_row["ebay_notes"] = f"{prev}; {note}".strip("; ")
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

    def _finish_auth(status: int, detail: str = "", partial_row: dict | None = None) -> list[dict]:
        return _finish_abort(
            note=f"aborted: invalid or revoked EBAY_SOLD_API_KEY / quota (HTTP {status})",
            message=(
                f"Invalid, revoked, or quota-blocked EBAY_SOLD_API_KEY (HTTP {status}). "
                "Fix the key in .env, upgrade plan, or remove it to soft-skip."
            ),
            detail=detail,
            partial_row=partial_row,
        )

    def _finish_rate_limit(
        retry_after: str = "", detail: str = "", partial_row: dict | None = None
    ) -> list[dict]:
        ra = f" Retry-After={retry_after}." if retry_after else ""
        return _finish_abort(
            note=f"aborted: rate limited HTTP 429"
            + (f" Retry-After={retry_after}" if retry_after else ""),
            message=(
                f"SoldComps rate limited (HTTP 429).{ra} "
                "Stopping remaining products to avoid burning quota. "
                "Wait and re-run, or rely on cache."
            ),
            detail=detail,
            partial_row=partial_row,
        )

    for product in products:
        name = product["name"]
        cat = product.get("category") or ""
        kws = product_ebay_keywords(product, max_kw)
        row = empty_row(name, cat, fetched_at=fetched_at)
        if not kws:
            row["ebay_notes"] = "no keywords"
            rows.append(row)
            print(f"  skip (no keywords): {name}")
            continue

        all_items: list[dict] = []
        primary_sold_items: list[dict] = []
        notes: list[str] = []
        for i, kw in enumerate(kws):
            ckey = f"sold|{site}|{kw}|{sold_after_90}|{count}"
            cached = cache_get(cache, ckey, ttl) if use_cache else None
            if cached is not None:
                items = list(cached.get("items") or [])
                cache_hits += 1
            else:
                try:
                    payload = fetch_soldcomps(
                        api_key,
                        kw,
                        sold=True,
                        sold_after=sold_after_90,
                        count=count,
                        ebay_site=site,
                        session=session,
                    )
                    api_calls += 1
                    items = list(payload.get("items") or [])
                    if use_cache:
                        cache_put(cache, ckey, {"items": items})
                except EbayAuthError as e:
                    row["ebay_keywords_used"] = " | ".join(kws)
                    row["ebay_notes"] = f"aborted: HTTP {e.status}"
                    return _finish_auth(e.status, e.detail, partial_row=row)
                except EbayRateLimitError as e:
                    row["ebay_keywords_used"] = " | ".join(kws)
                    row["ebay_notes"] = "aborted: HTTP 429"
                    return _finish_rate_limit(
                        e.retry_after, e.detail, partial_row=row
                    )
                except Exception as e:
                    notes.append(f"sold_fail:{kw}")
                    print(f"  [warn] sold search failed for {name!r} kw={kw!r}: {e}")
                    items = []
                time.sleep(delay_s)
            if i == 0:
                # Primary keyword only — used for sell-through numerator match
                primary_sold_items = list(items)
            # Multi-keyword aggregate for demand sold_count columns (dedupe)
            seen = {it.get("itemId") for it in all_items if it.get("itemId")}
            for it in items:
                iid = it.get("itemId")
                if iid and iid in seen:
                    continue
                if iid:
                    seen.add(iid)
                all_items.append(it)

        stats = aggregate_sold_items(all_items, now=now)
        row.update(stats)

        # Sell-through: primary keyword sold_90d / (primary sold_90d + active)
        # so numerator and denominator share the same search (kws[0]).
        sell_through = 0.0
        if settings["fetch_active_for_sell_through"] and kws:
            primary = kws[0]
            active_count = min(60, count)
            akey = f"active|{site}|{primary}|{active_count}"
            cached_a = cache_get(cache, akey, ttl) if use_cache else None
            if cached_a is not None:
                active_items = list(cached_a.get("items") or [])
                cache_hits += 1
            else:
                try:
                    payload_a = fetch_soldcomps(
                        api_key,
                        primary,
                        sold=False,
                        count=active_count,
                        ebay_site=site,
                        session=session,
                    )
                    api_calls += 1
                    active_items = list(payload_a.get("items") or [])
                    if use_cache:
                        cache_put(cache, akey, {"items": active_items})
                except EbayAuthError as e:
                    row["ebay_keywords_used"] = " | ".join(kws)
                    row["ebay_notes"] = "; ".join(
                        notes + [f"aborted: HTTP {e.status}"]
                    )
                    return _finish_auth(e.status, e.detail, partial_row=row)
                except EbayRateLimitError as e:
                    row["ebay_keywords_used"] = " | ".join(kws)
                    row["ebay_notes"] = "; ".join(notes + ["aborted: HTTP 429"])
                    return _finish_rate_limit(
                        e.retry_after, e.detail, partial_row=row
                    )
                except Exception as e:
                    notes.append("active_fail")
                    print(f"  [warn] active search failed for {name!r}: {e}")
                    active_items = []
                time.sleep(delay_s)
            primary_stats = aggregate_sold_items(primary_sold_items, now=now)
            n_sold = int(primary_stats.get("ebay_sold_count_90d") or 0)
            n_active = len(active_items)
            denom = n_sold + n_active
            if denom > 0:
                sell_through = round(n_sold / denom, 4)
        row["ebay_sell_through_proxy"] = sell_through
        row["ebay_keywords_used"] = " | ".join(kws)
        row["ebay_notes"] = "; ".join(notes)
        rows.append(row)
        print(
            f"  scanned: {name} -> 30d={row['ebay_sold_count_30d']} "
            f"90d={row['ebay_sold_count_90d']} "
            f"avg_price={row['ebay_avg_sold_price'] or '—'} "
            f"st={sell_through}"
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
        description="eBay sold-listings demand signal (SoldComps) for demand-monitor V2"
    )
    parser.add_argument("--config", default="config/products.yaml")
    parser.add_argument("--out", default="out/ebay_sold_signal.csv")
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
