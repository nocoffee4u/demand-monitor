#!/usr/bin/env python3
"""
x_scan.py
---------
Optional X (Twitter) demand signal: recent posts matching product keywords
and optional brand-account activity.

BACKENDS
  api     — official X API v2 recent search (requires X_BEARER_TOKEN)
  manual  — read rows from x_manual_log.csv (no API spend)
  auto    — api if token present, else manual if log has data, else zeros

COST (important, 2026):
  X API is pay-per-use for new developers (no practical free search tier).
  Recent search returns post objects billed as Post reads (~$0.005 each as of
  mid-2026 — check developer.x.com for current rates). Keep max_results low
  and run weekly. A 19-product scan at max_results=10 is typically a few
  dollars per week at most; dry-run first with --estimate.

USAGE:
  python3 x_scan.py --estimate          # print query plan + cost ceiling
  python3 x_scan.py                     # auto backend
  python3 x_scan.py --backend api
  python3 x_scan.py --backend manual
  python3 x_scan.py --smoke             # first product only

SETUP (API):
  1. Create a project/app at https://developer.x.com
  2. Load pay-per-use credits / attach a payment method
  3. Copy the Bearer Token into .env as X_BEARER_TOKEN=...
  4. Optionally set x.enabled: true in config/products.yaml

MANUAL fallback:
  Fill x_manual_log.csv each week (brand profile + keyword search in the
  X UI). Same idea as facebook_manual_log.csv.
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
import yaml

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

X_RECENT_SEARCH_URL = "https://api.x.com/2/tweets/search/recent"
USER_AGENT = "printshop-demand-scan/0.2 (+local research; x-api)"
DEFAULT_DELAY_S = 1.2
# Recent search window is last 7 days on standard access.
DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_MAX_RESULTS = 10
# Conservative public list price used only for --estimate (not billed here).
DEFAULT_COST_PER_POST_READ = 0.005


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def x_settings(cfg: dict) -> dict:
    x = cfg.get("x") or {}
    return {
        "enabled": x.get("enabled", True),
        "lookback_days": int(x.get("lookback_days") or DEFAULT_LOOKBACK_DAYS),
        "max_results": int(x.get("max_results") or DEFAULT_MAX_RESULTS),
        "brand_accounts": list(x.get("brand_accounts") or []),
        "brand_categories": list(x.get("brand_categories") or []),
        "cost_per_post_read": float(
            x.get("cost_per_post_read") or DEFAULT_COST_PER_POST_READ
        ),
    }


def product_x_keywords(product: dict) -> list[str]:
    """Prefer tighter x_keywords when present; else reuse product keywords."""
    kws = product.get("x_keywords") or product.get("keywords") or []
    return [k for k in kws if k and str(k).strip()][:3]


def build_search_query(keyword: str, brand_accounts: list[str] | None = None) -> str:
    """
    Build an X recent-search query. Keeps operators simple and billable-safe.
    """
    kw = (keyword or "").strip()
    # Prefer phrase match for multi-word product terms.
    if " " in kw and not kw.startswith('"'):
        core = f'"{kw}"'
    else:
        core = kw

    # Exclude retweets / replies to focus on original demand chatter.
    parts = [core, "-is:retweet", "-is:reply", "lang:en"]
    return " ".join(parts)


def build_brand_query(account: str, keyword: str | None = None) -> str:
    handle = account.lstrip("@")
    if keyword:
        kw = keyword.strip()
        if " " in kw and not kw.startswith('"'):
            kw = f'"{kw}"'
        return f"(from:{handle} OR @{handle}) {kw} -is:retweet lang:en"
    return f"(from:{handle} OR @{handle}) -is:retweet lang:en"


def empty_row(product_name: str, category: str = "") -> dict:
    return {
        "product": product_name,
        "category": category,
        "x_matching_posts": 0,
        "x_total_likes": 0,
        "x_total_replies": 0,
        "x_total_reposts": 0,
        "x_example_links": "",
        "x_backend": "none",
        "x_notes": "",
    }


def write_rows(rows: list[dict], out_path: str) -> None:
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    fieldnames = [
        "product",
        "category",
        "x_matching_posts",
        "x_total_likes",
        "x_total_replies",
        "x_total_reposts",
        "x_example_links",
        "x_backend",
        "x_notes",
    ]
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


# ---------------------------------------------------------------------------
# Manual log
# ---------------------------------------------------------------------------

def load_manual_log(path: str) -> dict[str, dict]:
    """
    Latest row per product (by week_of if present). Columns:
      week_of, product, rough_post_count, rough_engagement, notes
    """
    p = Path(path)
    if not p.exists():
        return {}
    by_product: dict[str, dict] = {}
    with p.open(newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("product") or "").strip()
            if not name or name.startswith("#"):
                continue
            # Keep last seen row for each product (file is chronological).
            by_product[name] = row
    return by_product


def scan_manual(cfg: dict, log_path: str) -> list[dict]:
    log = load_manual_log(log_path)
    rows = []
    for product in cfg.get("products") or []:
        name = product["name"]
        cat = product.get("category") or ""
        row = empty_row(name, cat)
        row["x_backend"] = "manual"
        entry = log.get(name)
        if not entry:
            row["x_notes"] = "no manual row"
            rows.append(row)
            continue
        try:
            posts = int(float(entry.get("rough_post_count") or 0))
        except ValueError:
            posts = 0
        try:
            eng = int(float(entry.get("rough_engagement") or 0))
        except ValueError:
            eng = 0
        row["x_matching_posts"] = posts
        # Split engagement roughly when only a total is logged.
        row["x_total_likes"] = eng
        row["x_notes"] = (entry.get("notes") or "").strip()
        rows.append(row)
        print(f"  manual: {name} -> posts={posts} eng={eng}")
    return rows


# ---------------------------------------------------------------------------
# Official API
# ---------------------------------------------------------------------------

def x_api_search(
    bearer: str,
    query: str,
    *,
    max_results: int,
    start_time: datetime | None,
    session: requests.Session,
) -> dict:
    headers = {
        "Authorization": f"Bearer {bearer}",
        "User-Agent": USER_AGENT,
    }
    params: dict = {
        "query": query,
        "max_results": max(10, min(100, max_results)),  # API min 10, max 100
        "tweet.fields": "public_metrics,created_at,lang",
    }
    if start_time is not None:
        # RFC3339, second precision
        params["start_time"] = start_time.astimezone(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

    resp = session.get(
        X_RECENT_SEARCH_URL, headers=headers, params=params, timeout=30
    )
    if resp.status_code == 429:
        reset = resp.headers.get("x-rate-limit-reset")
        raise RuntimeError(f"X API rate limited (429); reset={reset}")
    if resp.status_code == 401:
        raise RuntimeError("X API unauthorized (401) — check X_BEARER_TOKEN")
    if resp.status_code == 402:
        raise RuntimeError(
            "X API payment required (402) — add credits at developer.x.com"
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"X API HTTP {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def aggregate_posts(payload: dict) -> tuple[int, int, int, int, list[str]]:
    data = payload.get("data") or []
    likes = replies = reposts = 0
    links: list[str] = []
    for post in data:
        pm = post.get("public_metrics") or {}
        likes += int(pm.get("like_count") or 0)
        replies += int(pm.get("reply_count") or 0)
        reposts += int(pm.get("retweet_count") or 0)
        pid = post.get("id")
        if pid and len(links) < 3:
            links.append(f"https://x.com/i/web/status/{pid}")
    return len(data), likes, replies, reposts, links


def scan_api(cfg: dict, delay_s: float, smoke: bool = False) -> list[dict]:
    bearer = os.environ.get("X_BEARER_TOKEN", "").strip()
    if not bearer:
        print("ERROR: X_BEARER_TOKEN not set (copy from developer.x.com into .env)")
        sys.exit(1)

    settings = x_settings(cfg)
    products = list(cfg.get("products") or [])
    if smoke:
        products = products[:1]
        print(f"SMOKE mode: only product {products[0]['name']!r}")

    lookback = min(settings["lookback_days"], 7)  # recent search cap
    start_time = datetime.now(timezone.utc) - timedelta(days=lookback)
    max_results = settings["max_results"]
    brands = settings["brand_accounts"]
    brand_cats = set(settings["brand_categories"] or [])

    session = requests.Session()
    rows: list[dict] = []

    for product in products:
        name = product["name"]
        cat = product.get("category") or ""
        row = empty_row(name, cat)
        row["x_backend"] = "api"

        posts = likes = replies = reposts = 0
        links: list[str] = []
        notes: list[str] = []
        seen_ids: set[str] = set()

        queries: list[str] = []
        for kw in product_x_keywords(product):
            queries.append(build_search_query(kw))

        # Brand-scoped queries for matching categories (e.g. Rad Power parts).
        if brands and (not brand_cats or cat in brand_cats):
            for account in brands[:2]:
                for kw in product_x_keywords(product)[:1]:
                    queries.append(build_brand_query(account, kw))

        # De-dupe query strings
        uniq_q: list[str] = []
        seen_q: set[str] = set()
        for q in queries:
            if q not in seen_q:
                seen_q.add(q)
                uniq_q.append(q)

        for i, query in enumerate(uniq_q):
            if i:
                time.sleep(delay_s)
            try:
                payload = x_api_search(
                    bearer,
                    query,
                    max_results=max_results,
                    start_time=start_time,
                    session=session,
                )
            except Exception as e:
                notes.append(f"query_err:{e}")
                print(f"  [warn] {name}: {e}")
                continue

            for post in payload.get("data") or []:
                pid = post.get("id")
                if not pid or pid in seen_ids:
                    continue
                seen_ids.add(pid)
                pm = post.get("public_metrics") or {}
                posts += 1
                likes += int(pm.get("like_count") or 0)
                replies += int(pm.get("reply_count") or 0)
                reposts += int(pm.get("retweet_count") or 0)
                if len(links) < 3:
                    links.append(f"https://x.com/i/web/status/{pid}")

            meta = payload.get("meta") or {}
            result_count = meta.get("result_count", len(payload.get("data") or []))
            print(f"  api: {name} q={query[:60]!r}… -> {result_count}")

        row["x_matching_posts"] = posts
        row["x_total_likes"] = likes
        row["x_total_replies"] = replies
        row["x_total_reposts"] = reposts
        row["x_example_links"] = " | ".join(links)
        row["x_notes"] = "; ".join(notes)[:300]
        rows.append(row)
        print(f"  done: {name} -> posts={posts} likes={likes}")

    return rows


def estimate(cfg: dict) -> None:
    settings = x_settings(cfg)
    products = list(cfg.get("products") or [])
    brands = settings["brand_accounts"]
    brand_cats = set(settings["brand_categories"] or [])
    max_results = max(10, min(100, settings["max_results"]))
    cost = settings["cost_per_post_read"]

    n_queries = 0
    plan: list[str] = []
    for product in products:
        kws = product_x_keywords(product)
        n_queries += len(kws)
        for kw in kws:
            plan.append(f"  search: {build_search_query(kw)[:90]}")
        cat = product.get("category") or ""
        if brands and (not brand_cats or cat in brand_cats):
            for account in brands[:2]:
                if kws:
                    n_queries += 1
                    plan.append(
                        f"  brand:  {build_brand_query(account, kws[0])[:90]}"
                    )

    ceiling_posts = n_queries * max_results
    ceiling_usd = ceiling_posts * cost
    print("=== X scan cost estimate (ceiling, not a quote) ===")
    print(f"products:           {len(products)}")
    print(f"search queries:     {n_queries}")
    print(f"max_results/query:  {max_results}")
    print(f"post-read ceiling:  {ceiling_posts}")
    print(f"@ ~${cost:.3f}/post:   ~${ceiling_usd:.2f} worst case this run")
    print(
        "Actual spend is usually lower (many queries return < max_results)."
    )
    print("\nQuery plan (truncated):")
    for line in plan[:40]:
        print(line)
    if len(plan) > 40:
        print(f"  … +{len(plan) - 40} more")


def resolve_backend(requested: str) -> str:
    if requested != "auto":
        return requested
    if os.environ.get("X_BEARER_TOKEN", "").strip():
        return "api"
    return "manual"


def scan(
    config_path: str,
    out_path: str,
    *,
    backend: str = "auto",
    manual_log: str = "x_manual_log.csv",
    delay_s: float = DEFAULT_DELAY_S,
    smoke: bool = False,
) -> None:
    cfg = load_config(config_path)
    settings = x_settings(cfg)

    if not settings["enabled"]:
        print("x.enabled is false — writing zero rows")
        rows = [
            empty_row(p["name"], p.get("category") or "")
            for p in (cfg.get("products") or [])
        ]
        for r in rows:
            r["x_backend"] = "disabled"
            r["x_notes"] = "x.enabled=false"
        write_rows(rows, out_path)
        print(f"Wrote {len(rows)} rows to {out_path}")
        return

    resolved = resolve_backend(backend)
    print(f"X backend: {resolved}")

    if resolved == "api":
        rows = scan_api(cfg, delay_s=delay_s, smoke=smoke)
    elif resolved == "manual":
        rows = scan_manual(cfg, manual_log)
    else:
        print(f"ERROR: unknown backend {resolved!r}")
        sys.exit(1)

    write_rows(rows, out_path)
    total_posts = sum(int(r["x_matching_posts"]) for r in rows)
    print(f"\nWrote {len(rows)} rows to {out_path} (total posts={total_posts})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Scan X (Twitter) for product demand chatter."
    )
    parser.add_argument("--config", default="config/products.yaml")
    parser.add_argument("--out", default="out/x_signal.csv")
    parser.add_argument(
        "--backend",
        choices=["auto", "api", "manual"],
        default="auto",
        help="auto = api if X_BEARER_TOKEN set, else manual log",
    )
    parser.add_argument(
        "--manual-log",
        default="x_manual_log.csv",
        help="CSV for --backend manual",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY_S,
        help=f"Seconds between API calls (default {DEFAULT_DELAY_S})",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Only first product (API debug)",
    )
    parser.add_argument(
        "--estimate",
        action="store_true",
        help="Print query plan and cost ceiling, then exit",
    )
    args = parser.parse_args()

    if args.estimate:
        estimate(load_config(args.config))
        sys.exit(0)

    scan(
        args.config,
        args.out,
        backend=args.backend,
        manual_log=args.manual_log,
        delay_s=args.delay,
        smoke=args.smoke,
    )
