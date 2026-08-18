#!/usr/bin/env python3
"""
amazon_scan.py
--------------
Optional Amazon commercial-intent + problem/replacement language signal.

v1 provider strategy (documented — soft-fail first):
  1. FREE (no key): Amazon public autocomplete
     GET https://completion.amazon.com/api/2017/suggestions
     → amazon_autocomplete_hits, problem language score from suggestion text,
       top suggestion as title proxy.
  2. OPTIONAL (paid third-party): Rainforest API search when
     RAINFOREST_API_KEY (or AMAZON_RAINFOREST_API_KEY) is set
     → amazon_listing_count (total results), amazon_avg_price, better top title.
     Not full review mining; only search titles/snippets when returned.
  3. Product Advertising API (Associates) is NOT implemented in v1 —
     requires approved Associates + signed AWS requests; document for later.

What this does NOT provide:
  - Invented Best Seller Rank / sold counts
  - Full review scraping or Playwright
  - Guaranteed search density without Rainforest key

SETUP:
  Free path works with no credentials (rate-limit politely; weekly cache).
  Optional listings/prices:
    RAINFOREST_API_KEY=...   # https://www.rainforestapi.com/

USAGE:
  python3 amazon_scan.py --estimate
  python3 amazon_scan.py
  python3 amazon_scan.py --smoke
  SKIP_AMAZON=1 ./run_all.sh

Cache: cache/amazon_cache.json (default TTL 28 days)
Soft-fail: blocked / empty / missing optional key → zeros + notes, exit 0.
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import requests
import yaml

from cache_utils import cache_get, cache_put, load_cache, save_cache

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)
# Amazon US marketplace id (public completion endpoint)
AMAZON_MID = "ATVPDKIKX0DER"
COMPLETION_URL = "https://completion.amazon.com/api/2017/suggestions"
RAINFOREST_URL = "https://api.rainforestapi.com/request"

DEFAULT_KEYWORDS_PER_PRODUCT = 3
DEFAULT_DELAY_S = 0.6
DEFAULT_CACHE_TTL_DAYS = 28
CACHE_PATH = Path("cache/amazon_cache.json")

# Problem / replacement language for commercial + pain intent
PROBLEM_TERMS = re.compile(
    r"\b("
    r"replace|replacement|spare|cover|cap|clip|mount|guard|protector|"
    r"broken|broke|crack|fail|loose|missing|lost|wear|worn|dust|"
    r"fuse|terminal|adapter|bracket|holder|widener|extender|kit"
    r")\b",
    re.I,
)

FIELDNAMES = [
    "product",
    "category",
    "amazon_listing_count",
    "amazon_autocomplete_hits",
    "amazon_problem_mention_score",
    "amazon_avg_price",
    "amazon_top_title",
    "amazon_keywords_used",
    "amazon_notes",
    "amazon_fetched_at",
]


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def amazon_settings(cfg: dict) -> dict:
    a = cfg.get("amazon") or {}
    return {
        "enabled": a.get("enabled", True),
        "keywords_per_product": int(
            a.get("keywords_per_product") or DEFAULT_KEYWORDS_PER_PRODUCT
        ),
        "cache_ttl_days": int(a.get("cache_ttl_days") or DEFAULT_CACHE_TTL_DAYS),
        "use_cache": bool(a.get("use_cache", True)),
        "amazon_domain": str(a.get("amazon_domain") or "amazon.com"),
    }


def product_amazon_keywords(product: dict, max_kw: int) -> list[str]:
    """
    amazon_keywords → keywords → search_volume_keywords (cap for quota).
    Prefer problem-oriented phrases when present; otherwise lightly bias the
    first generic phrase with a 'replacement' companion if room remains.
    """
    ordered: list[str] = []
    for key in ("amazon_keywords", "keywords", "search_volume_keywords"):
        for k in product.get(key) or []:
            s = str(k).strip()
            if s and s not in ordered:
                ordered.append(s)
            if len(ordered) >= max_kw:
                break
        if len(ordered) >= max_kw:
            break

    # Prefer problem-oriented first
    def _problem_rank(s: str) -> int:
        return 0 if PROBLEM_TERMS.search(s) else 1

    ordered.sort(key=_problem_rank)

    # If still have a free slot and nothing problem-oriented, add a
    # replacement-flavored variant of the first phrase (no invent of results).
    if ordered and len(ordered) < max_kw:
        if not any(PROBLEM_TERMS.search(s) for s in ordered):
            base = ordered[0]
            variant = f"{base} replacement"
            if variant not in ordered:
                ordered.append(variant)

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
        "amazon_listing_count": 0,
        "amazon_autocomplete_hits": 0,
        "amazon_problem_mention_score": 0,
        "amazon_avg_price": "",
        "amazon_top_title": "",
        "amazon_keywords_used": "",
        "amazon_notes": notes,
        "amazon_fetched_at": fetched_at
        or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def write_rows(rows: list[dict], out_path: str) -> None:
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDNAMES})


def get_rainforest_key() -> str | None:
    for env in ("RAINFOREST_API_KEY", "AMAZON_RAINFOREST_API_KEY"):
        v = os.environ.get(env, "").strip()
        if v:
            return v
    return None


def score_problem_language(texts: list[str]) -> int:
    """
    0–100 absolute score from fraction of texts with problem/replacement terms
    and density of matches. Does not invent review counts.
    """
    clean = [t for t in texts if (t or "").strip()]
    n = len(clean)
    if n <= 0:
        return 0
    hits = 0
    match_total = 0
    for t in clean:
        found = PROBLEM_TERMS.findall(t)
        if found:
            hits += 1
            match_total += len(found)
    frac = hits / n
    density = min(1.0, match_total / max(1.0, n * 2.0))
    raw = min(100.0, frac * 70.0 + density * 30.0)
    # Shrinkage so one matching suggestion can't equal strong multi-hit evidence
    return int(round(raw * min(1.0, n / 4.0)))


def fetch_autocomplete(
    prefix: str,
    *,
    session: requests.Session,
    timeout: float = 20.0,
) -> list[str]:
    """Public Amazon completion suggestions (no API key)."""
    params = {
        "mid": AMAZON_MID,
        "alias": "aps",
        "prefix": prefix,
        "limit": 11,
        "suggestion-type": "KEYWORD",
        "lop": "en_US",
        "site-variant": "desktop",
        "client-info": "amazon-search-ui",
    }
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/javascript,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://www.amazon.com",
        "Referer": "https://www.amazon.com/",
    }
    resp = session.get(COMPLETION_URL, params=params, headers=headers, timeout=timeout)
    if resp.status_code == 429:
        raise RuntimeError("Amazon autocomplete rate limited (429)")
    if resp.status_code >= 400:
        raise RuntimeError(
            f"Amazon autocomplete HTTP {resp.status_code}: {(resp.text or '')[:200]}"
        )
    data = resp.json() if resp.content else {}
    out: list[str] = []
    for s in data.get("suggestions") or []:
        if isinstance(s, dict):
            val = (s.get("value") or s.get("keyword") or "").strip()
        else:
            val = str(s).strip()
        if val and val not in out:
            out.append(val)
    return out


def fetch_rainforest_search(
    api_key: str,
    term: str,
    *,
    amazon_domain: str,
    session: requests.Session,
    timeout: float = 45.0,
) -> dict[str, Any]:
    """
    Rainforest type=search. Returns listing_count, avg_price, top_title, titles.
    Soft errors raise RuntimeError for caller to note.
    """
    params = {
        "api_key": api_key,
        "type": "search",
        "amazon_domain": amazon_domain,
        "search_term": term,
    }
    resp = session.get(RAINFOREST_URL, params=params, timeout=timeout)
    if resp.status_code in (401, 403):
        raise RuntimeError(f"Rainforest auth HTTP {resp.status_code}")
    if resp.status_code == 429:
        raise RuntimeError("Rainforest rate limited (429)")
    if resp.status_code >= 400:
        raise RuntimeError(
            f"Rainforest HTTP {resp.status_code}: {(resp.text or '')[:200]}"
        )
    data = resp.json() if resp.content else {}
    if data.get("request_info") and not data["request_info"].get("success", True):
        msg = data.get("request_info", {}).get("message") or "Rainforest request failed"
        raise RuntimeError(str(msg)[:200])

    search = data.get("search_results") or []
    pagination = data.get("pagination") or {}
    total = pagination.get("total_results")
    if total is None:
        # Some responses only return page size
        total = len(search) if search else 0
    try:
        total_i = int(total)
    except (TypeError, ValueError):
        total_i = len(search)

    prices: list[float] = []
    titles: list[str] = []
    for item in search:
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or "").strip()
        if title:
            titles.append(title[:200])
        price = item.get("price") or {}
        if isinstance(price, dict):
            val = price.get("value")
            try:
                if val is not None:
                    prices.append(float(val))
            except (TypeError, ValueError):
                pass

    avg_price = round(statistics.mean(prices), 2) if prices else None
    top_title = titles[0] if titles else ""
    return {
        "listing_count": total_i,
        "avg_price": avg_price,
        "top_title": top_title,
        "titles": titles[:15],
    }


def estimate(cfg: dict) -> None:
    settings = amazon_settings(cfg)
    products = list(cfg.get("products") or [])
    max_kw = settings["keywords_per_product"]
    n_kw = sum(len(product_amazon_keywords(p, max_kw)) for p in products)
    n_prod = len(products)
    has_rf = bool(get_rainforest_key())
    print("Amazon scan estimate (cold cache):")
    print(f"  products:                 {n_prod}")
    print(f"  keywords (max {max_kw}/product): ~{n_kw}")
    print(f"  free autocomplete GETs:   ~{n_kw}  (completion.amazon.com)")
    if has_rf:
        print(f"  Rainforest search GETs:   ~{n_kw}  (RAINFOREST_API_KEY set)")
    else:
        print(
            "  Rainforest search GETs:   0  (set RAINFOREST_API_KEY for "
            "listing density + prices)"
        )
    print(f"  cache TTL:                {settings['cache_ttl_days']}d → {CACHE_PATH}")
    print("  PA-API / Associates:      not used in v1")
    print("  Soft-fail: blocked or empty → zeros + notes, exit 0")


def scan(
    config_path: str,
    out_path: str,
    *,
    smoke: bool = False,
    delay_s: float = DEFAULT_DELAY_S,
    no_cache: bool = False,
) -> list[dict]:
    cfg = load_config(config_path)
    settings = amazon_settings(cfg)
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
                "skipped: amazon.enabled=false",
                fetched_at,
            )
            for p in products
        ]
        write_rows(rows, out_path)
        print(f"Amazon disabled in config — wrote empty rows to {out_path}")
        return rows

    max_kw = settings["keywords_per_product"]
    use_cache = settings["use_cache"] and not no_cache
    ttl = settings["cache_ttl_days"]
    domain = settings["amazon_domain"]
    cache = load_cache(CACHE_PATH) if use_cache else {}
    session = requests.Session()
    rf_key = get_rainforest_key()

    rows: list[dict] = []
    ac_calls = 0
    rf_calls = 0
    cache_hits = 0

    for product in products:
        name = product["name"]
        cat = product.get("category") or ""
        kws = product_amazon_keywords(product, max_kw)
        if not kws:
            rows.append(
                empty_row(name, cat, "skipped: no keywords", fetched_at)
            )
            print(f"  skip (no keywords): {name}")
            continue

        all_suggestions: list[str] = []
        all_titles: list[str] = []
        listing_max = 0
        prices: list[float] = []
        notes: list[str] = []
        top_title = ""
        any_ok = False

        for kw in kws:
            ckey = f"ac:{quote_plus(kw.lower())}"
            cached = cache_get(cache, ckey, ttl) if use_cache else None
            if cached is not None:
                cache_hits += 1
                sugg = list(cached.get("suggestions") or [])
                notes.append(f"cache_hit:{kw[:40]}")
            else:
                try:
                    sugg = fetch_autocomplete(kw, session=session)
                    ac_calls += 1
                    if use_cache:
                        cache_put(cache, ckey, {"suggestions": sugg})
                    time.sleep(delay_s)
                except Exception as e:
                    notes.append(f"autocomplete_err:{kw[:30]}:{e}")
                    sugg = []
                    time.sleep(min(delay_s, 1.0))

            if sugg:
                any_ok = True
                all_suggestions.extend(sugg)
                if not top_title:
                    top_title = sugg[0][:200]

            if rf_key:
                rkey = f"rf:{domain}:{quote_plus(kw.lower())}"
                rcached = cache_get(cache, rkey, ttl) if use_cache else None
                if rcached is not None:
                    cache_hits += 1
                    listing_max = max(
                        listing_max, int(rcached.get("listing_count") or 0)
                    )
                    if rcached.get("avg_price") is not None:
                        try:
                            prices.append(float(rcached["avg_price"]))
                        except (TypeError, ValueError):
                            pass
                    if rcached.get("top_title") and not top_title:
                        top_title = str(rcached["top_title"])[:200]
                    all_titles.extend(list(rcached.get("titles") or []))
                else:
                    try:
                        rf = fetch_rainforest_search(
                            rf_key, kw, amazon_domain=domain, session=session
                        )
                        rf_calls += 1
                        if use_cache:
                            cache_put(cache, rkey, rf)
                        listing_max = max(listing_max, int(rf.get("listing_count") or 0))
                        if rf.get("avg_price") is not None:
                            prices.append(float(rf["avg_price"]))
                        if rf.get("top_title"):
                            if not top_title or listing_max:
                                top_title = str(rf["top_title"])[:200]
                        all_titles.extend(list(rf.get("titles") or []))
                        any_ok = True
                        time.sleep(delay_s)
                    except Exception as e:
                        notes.append(f"rainforest_err:{kw[:30]}:{e}")
                        time.sleep(min(delay_s, 1.0))

        # Unique suggestion count
        uniq_sugg = list(dict.fromkeys(all_suggestions))
        problem_texts = uniq_sugg + all_titles
        problem_score = score_problem_language(problem_texts)

        avg_price = ""
        if prices:
            avg_price = round(statistics.mean(prices), 2)

        if not rf_key:
            notes.append("no_rainforest_key:listing_count=0")
        if not any_ok and not uniq_sugg:
            notes.append("soft-fail:no autocomplete/search data")

        row = {
            "product": name,
            "category": cat,
            "amazon_listing_count": listing_max if rf_key else 0,
            "amazon_autocomplete_hits": len(uniq_sugg),
            "amazon_problem_mention_score": problem_score,
            "amazon_avg_price": avg_price,
            "amazon_top_title": top_title,
            "amazon_keywords_used": " | ".join(kws),
            "amazon_notes": "; ".join(notes)[:500],
            "amazon_fetched_at": fetched_at,
        }
        rows.append(row)
        print(
            f"  {name[:48]}: ac={len(uniq_sugg)} problem={problem_score} "
            f"listings={row['amazon_listing_count']} "
            f"{'(rf)' if rf_key else '(ac-only)'}"
        )

    if use_cache:
        save_cache(CACHE_PATH, cache)

    write_rows(rows, out_path)
    print(
        f"\nWrote {len(rows)} rows → {out_path} "
        f"(autocomplete_calls={ac_calls}, rainforest_calls={rf_calls}, "
        f"cache_hits={cache_hits})"
    )
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Amazon commercial-intent / problem-language demand signal."
    )
    parser.add_argument("--config", default="config/products.yaml")
    parser.add_argument("--out", default="out/amazon_signal.csv")
    parser.add_argument("--estimate", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY_S)
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args()

    try:
        cfg = load_config(args.config)
        if args.estimate:
            estimate(cfg)
            sys.exit(0)
        scan(
            args.config,
            args.out,
            smoke=args.smoke,
            delay_s=args.delay,
            no_cache=args.no_cache,
        )
        sys.exit(0)
    except Exception as e:
        # Soft-fail whole scanner for weekly pipeline safety
        print(f"WARN: amazon_scan failed soft: {e}", file=sys.stderr)
        try:
            cfg = load_config(args.config)
            products = list(cfg.get("products") or [])
            if args.smoke:
                products = products[:1]
            fa = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            rows = [
                empty_row(p["name"], p.get("category") or "", f"soft-fail:{e}", fa)
                for p in products
            ]
            write_rows(rows, args.out)
        except Exception:
            write_rows([], args.out)
        sys.exit(0)
