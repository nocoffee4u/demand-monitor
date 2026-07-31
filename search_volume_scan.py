#!/usr/bin/env python3
"""
search_volume_scan.py
---------------------
Pulls Google Ads keyword metrics via DataForSEO for every product keyword:
  - monthly search volume
  - competition (LOW/MEDIUM/HIGH + 0-100 index)
  - CPC

API: DataForSEO Keywords Data → Google Ads → Search Volume
  Standard queue (default, cheaper): task_post + poll task_get
  Live mode (--live): single request, higher cost, ~seconds

Pricing (check dataforseo.com for current rates; used only by --estimate):
  Standard ≈ $0.05–0.06 per task (up to 1,000 keywords per task)
  Live     ≈ $0.075–0.09 per task

Cache: cache/search_volume_cache.json (keyword+location+language → metrics).
Default refresh: 7 days. Only uncached/stale keywords hit the API.

USAGE:
  python3 search_volume_scan.py --estimate
  python3 search_volume_scan.py                  # standard queue, uses cache
  python3 search_volume_scan.py --live           # faster, costs more
  python3 search_volume_scan.py --force-refresh  # ignore cache age
  python3 search_volume_scan.py --cache-only     # no API calls; fail if gaps

SETUP:
  1. Create account at https://app.dataforseo.com/api-access
  2. Put login + password in .env:
       DATAFORSEO_LOGIN=...
       DATAFORSEO_PASSWORD=...
  3. Optionally tune config/products.yaml → search_volume:

OUTPUT:
  out/search_volume_signal.csv     one row per product (for score_demand.py)
  out/search_volume_keywords.csv   one row per keyword (audit / debug)
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
import yaml

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

BASE_URL = "https://api.dataforseo.com/v3"
TASK_POST = f"{BASE_URL}/keywords_data/google_ads/search_volume/task_post"
TASK_GET = f"{BASE_URL}/keywords_data/google_ads/search_volume/task_get"
TASK_LIVE = f"{BASE_URL}/keywords_data/google_ads/search_volume/live"

# Conservative public list prices for --estimate only (not billed by this script).
DEFAULT_COST_STANDARD = 0.05
DEFAULT_COST_LIVE = 0.075

DEFAULT_CACHE_PATH = "cache/search_volume_cache.json"
DEFAULT_OUT_PRODUCTS = "out/search_volume_signal.csv"
DEFAULT_OUT_KEYWORDS = "out/search_volume_keywords.csv"
DEFAULT_CACHE_TTL_DAYS = 7
DEFAULT_LOCATION_CODE = 2840  # United States
DEFAULT_LANGUAGE_CODE = "en"
MAX_KEYWORDS_PER_TASK = 1000
MAX_KEYWORD_CHARS = 80
MAX_KEYWORD_WORDS = 10


# ---------------------------------------------------------------------------
# Config / credentials
# ---------------------------------------------------------------------------

def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def sv_settings(cfg: dict) -> dict:
    s = cfg.get("search_volume") or {}
    return {
        "enabled": s.get("enabled", True),
        "location_code": int(s.get("location_code") or DEFAULT_LOCATION_CODE),
        "location_name": s.get("location_name"),  # optional override
        "language_code": str(s.get("language_code") or DEFAULT_LANGUAGE_CODE),
        "cache_ttl_days": int(s.get("cache_ttl_days") or DEFAULT_CACHE_TTL_DAYS),
        "cache_path": str(s.get("cache_path") or DEFAULT_CACHE_PATH),
        "queue": str(s.get("queue") or "standard").lower(),  # standard | live
        "cost_standard": float(s.get("cost_standard") or DEFAULT_COST_STANDARD),
        "cost_live": float(s.get("cost_live") or DEFAULT_COST_LIVE),
        "poll_interval_s": float(s.get("poll_interval_s") or 15.0),
        "poll_timeout_s": float(s.get("poll_timeout_s") or 3600.0),
        "search_partners": bool(s.get("search_partners", False)),
    }


def get_credentials() -> tuple[str, str]:
    login = (os.environ.get("DATAFORSEO_LOGIN") or "").strip()
    password = (os.environ.get("DATAFORSEO_PASSWORD") or "").strip()
    if not login or not password:
        print(
            "ERROR: set DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD in .env\n"
            "  Get them from https://app.dataforseo.com/api-access"
        )
        sys.exit(1)
    return login, password


# ---------------------------------------------------------------------------
# Keyword collection
# ---------------------------------------------------------------------------

def normalize_keyword(kw: str) -> str | None:
    """Sanitize for Google Ads limits; return None if unusable."""
    if not kw:
        return None
    k = " ".join(str(kw).strip().lower().split())
    if not k:
        return None
    # Strip characters Google Ads often rejects (keep alphanumerics, spaces, -')
    cleaned = "".join(
        ch if ch.isalnum() or ch in " -'&./" else " " for ch in k
    )
    cleaned = " ".join(cleaned.split())
    if not cleaned:
        return None
    words = cleaned.split()
    if len(words) > MAX_KEYWORD_WORDS:
        cleaned = " ".join(words[:MAX_KEYWORD_WORDS])
    if len(cleaned) > MAX_KEYWORD_CHARS:
        cleaned = cleaned[:MAX_KEYWORD_CHARS].rsplit(" ", 1)[0]
    return cleaned or None


def product_keywords(product: dict) -> list[str]:
    """
    Keywords used for search volume.
    Prefer search_volume_keywords when set; else discovery keywords.
    Does NOT use marketplace_keywords (those are competition-tight, often
    too brand-specific for Google Ads volume).
    """
    raw = product.get("search_volume_keywords") or product.get("keywords") or []
    out: list[str] = []
    seen: set[str] = set()
    for kw in raw:
        n = normalize_keyword(kw)
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def collect_all_keywords(cfg: dict) -> tuple[list[str], dict[str, list[str]]]:
    """Return (unique_keywords, product_name → keywords)."""
    by_product: dict[str, list[str]] = {}
    all_kws: list[str] = []
    seen: set[str] = set()
    for product in cfg.get("products") or []:
        name = product["name"]
        kws = product_keywords(product)
        by_product[name] = kws
        for k in kws:
            if k not in seen:
                seen.add(k)
                all_kws.append(k)
    return all_kws, by_product


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def cache_key(keyword: str, location_code: int, language_code: str) -> str:
    return f"{location_code}:{language_code}:{keyword}"


def load_cache(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {"version": 1, "entries": {}}
    try:
        with p.open() as f:
            data = json.load(f)
        if "entries" not in data:
            return {"version": 1, "entries": {}}
        return data
    except (json.JSONDecodeError, OSError) as e:
        print(f"  [warn] cache unreadable ({e}); starting fresh")
        return {"version": 1, "entries": {}}


def save_cache(path: str, cache: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    with tmp.open("w") as f:
        json.dump(cache, f, indent=2, sort_keys=True)
    tmp.replace(p)


def entry_is_fresh(entry: dict, ttl_days: int, force: bool) -> bool:
    if force:
        return False
    fetched = entry.get("fetched_at")
    if not fetched:
        return False
    try:
        ts = datetime.fromisoformat(fetched.replace("Z", "+00:00"))
    except ValueError:
        return False
    age = datetime.now(timezone.utc) - ts.astimezone(timezone.utc)
    return age.total_seconds() < ttl_days * 86400


def partition_keywords(
    keywords: list[str],
    cache: dict,
    settings: dict,
    force_refresh: bool,
) -> tuple[list[str], list[str]]:
    """Return (cached_fresh, need_fetch)."""
    fresh: list[str] = []
    need: list[str] = []
    entries = cache.get("entries") or {}
    loc = settings["location_code"]
    lang = settings["language_code"]
    ttl = settings["cache_ttl_days"]
    for kw in keywords:
        key = cache_key(kw, loc, lang)
        entry = entries.get(key)
        if entry and entry_is_fresh(entry, ttl, force_refresh):
            fresh.append(kw)
        else:
            need.append(kw)
    return fresh, need


# ---------------------------------------------------------------------------
# DataForSEO client
# ---------------------------------------------------------------------------

def api_request(
    method: str,
    url: str,
    login: str,
    password: str,
    *,
    json_body: Any = None,
    timeout: float = 60.0,
    retries: int = 4,
) -> dict:
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            resp = requests.request(
                method,
                url,
                auth=(login, password),
                json=json_body,
                headers={"Content-Type": "application/json"},
                timeout=timeout,
            )
            if resp.status_code in (429, 502, 503, 504):
                sleep_s = min(90.0, (2**attempt) * 5.0)
                print(
                    f"  [warn] HTTP {resp.status_code} (attempt {attempt + 1}/"
                    f"{retries}); sleep {sleep_s:.0f}s"
                )
                time.sleep(sleep_s)
                last_err = RuntimeError(f"HTTP {resp.status_code}")
                continue
            try:
                payload = resp.json()
            except ValueError:
                raise RuntimeError(
                    f"non-JSON response HTTP {resp.status_code}: {resp.text[:200]}"
                )
            # DataForSEO wraps errors in status_code even on HTTP 200
            return payload
        except requests.RequestException as e:
            last_err = e
            sleep_s = min(60.0, (2**attempt) * 3.0)
            print(f"  [warn] network error: {e}; sleep {sleep_s:.0f}s")
            time.sleep(sleep_s)
    raise RuntimeError(f"DataForSEO request failed after {retries} tries: {last_err}")


def build_task_payload(keywords: list[str], settings: dict) -> dict:
    task: dict[str, Any] = {
        "keywords": keywords,
        "language_code": settings["language_code"],
        "search_partners": settings["search_partners"],
    }
    if settings.get("location_name"):
        task["location_name"] = settings["location_name"]
    else:
        task["location_code"] = settings["location_code"]
    return task


def post_standard_task(
    keywords: list[str],
    settings: dict,
    login: str,
    password: str,
) -> str:
    payload = [build_task_payload(keywords, settings)]
    resp = api_request("POST", TASK_POST, login, password, json_body=payload)
    if resp.get("status_code") != 20000:
        raise RuntimeError(
            f"task_post failed: {resp.get('status_code')} {resp.get('status_message')}"
        )
    tasks = resp.get("tasks") or []
    if not tasks:
        raise RuntimeError("task_post returned no tasks")
    task = tasks[0]
    if task.get("status_code") not in (20000, 20100):
        raise RuntimeError(
            f"task create error: {task.get('status_code')} {task.get('status_message')}"
        )
    task_id = task.get("id")
    if not task_id:
        raise RuntimeError("task_post missing task id")
    cost = task.get("cost") or resp.get("cost")
    print(f"  posted standard task {task_id} (cost reported: ${cost})")
    return task_id


# DataForSEO "still working" codes — keep polling (not fatal errors).
# 20100 Task Created, 40601 Task Handed, 40602 Task In Queue
PENDING_TASK_CODES = {20100, 40601, 40602}


def poll_task(
    task_id: str,
    settings: dict,
    login: str,
    password: str,
) -> list[dict]:
    """Poll until status 20000 or timeout. Returns result array."""
    deadline = time.time() + settings["poll_timeout_s"]
    interval = settings["poll_interval_s"]
    url = f"{TASK_GET}/{task_id}"
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        resp = api_request("GET", url, login, password)
        if resp.get("status_code") != 20000:
            print(
                f"  [warn] task_get envelope: {resp.get('status_code')} "
                f"{resp.get('status_message')}"
            )
            time.sleep(interval)
            continue
        tasks = resp.get("tasks") or []
        if not tasks:
            time.sleep(interval)
            continue
        task = tasks[0]
        code = int(task.get("status_code") or 0)
        msg = task.get("status_message")
        # 20000 = Ok (ready)
        if code == 20000:
            result = task.get("result")
            if result is None:
                print(f"  [warn] task ready but result null; re-poll ({msg})")
                time.sleep(interval)
                continue
            print(f"  task ready after {attempt} poll(s); {len(result)} keyword rows")
            return result
        # Still queued / processing — wait (do NOT treat 40602 as failure)
        if code in PENDING_TASK_CODES or 10000 <= code < 40000:
            if attempt == 1 or attempt % 4 == 0:
                print(f"  waiting… status={code} {msg} (poll {attempt})")
            time.sleep(interval)
            continue
        # True hard failures (e.g. 401xx auth, 5xxxx internal)
        raise RuntimeError(f"task failed: {code} {msg}")
    raise TimeoutError(
        f"task {task_id} not ready within {settings['poll_timeout_s']:.0f}s"
    )


def fetch_task_result(
    task_id: str,
    login: str,
    password: str,
) -> list[dict]:
    """One-shot GET of a previously posted task (no charge). Raises if not ready."""
    url = f"{TASK_GET}/{task_id}"
    resp = api_request("GET", url, login, password)
    if resp.get("status_code") != 20000:
        raise RuntimeError(
            f"task_get failed: {resp.get('status_code')} {resp.get('status_message')}"
        )
    tasks = resp.get("tasks") or []
    if not tasks:
        raise RuntimeError("task_get returned no tasks")
    task = tasks[0]
    code = int(task.get("status_code") or 0)
    msg = task.get("status_message")
    if code in PENDING_TASK_CODES:
        raise RuntimeError(f"task still pending: {code} {msg}")
    if code != 20000:
        raise RuntimeError(f"task failed: {code} {msg}")
    result = task.get("result")
    if result is None:
        raise RuntimeError("task ready but result is null")
    return result


def run_live(
    keywords: list[str],
    settings: dict,
    login: str,
    password: str,
) -> list[dict]:
    payload = [build_task_payload(keywords, settings)]
    resp = api_request(
        "POST", TASK_LIVE, login, password, json_body=payload, timeout=120.0
    )
    if resp.get("status_code") != 20000:
        raise RuntimeError(
            f"live failed: {resp.get('status_code')} {resp.get('status_message')}"
        )
    tasks = resp.get("tasks") or []
    if not tasks:
        raise RuntimeError("live returned no tasks")
    task = tasks[0]
    if task.get("status_code") != 20000:
        raise RuntimeError(
            f"live task error: {task.get('status_code')} {task.get('status_message')}"
        )
    cost = task.get("cost") or resp.get("cost")
    result = task.get("result") or []
    print(f"  live complete (cost reported: ${cost}); {len(result)} keyword rows")
    return result


def result_rows_to_cache_entries(
    result: list[dict],
    settings: dict,
    fetched_at: str,
) -> dict[str, dict]:
    """Map API result rows → cache entries keyed by cache_key."""
    loc = settings["location_code"]
    lang = settings["language_code"]
    out: dict[str, dict] = {}
    for row in result:
        kw = normalize_keyword(row.get("keyword") or "")
        if not kw:
            continue
        entry = {
            "keyword": kw,
            "spell": row.get("spell"),
            "search_volume": row.get("search_volume"),
            "competition": row.get("competition"),
            "competition_index": row.get("competition_index"),
            "cpc": row.get("cpc"),
            "low_top_of_page_bid": row.get("low_top_of_page_bid"),
            "high_top_of_page_bid": row.get("high_top_of_page_bid"),
            "monthly_searches": row.get("monthly_searches"),
            "location_code": row.get("location_code") or loc,
            "language_code": row.get("language_code") or lang,
            "fetched_at": fetched_at,
            "source": "dataforseo_google_ads",
        }
        out[cache_key(kw, loc, lang)] = entry
    return out


def mark_missing_as_zero(
    keywords: list[str],
    found_keys: set[str],
    settings: dict,
    fetched_at: str,
) -> dict[str, dict]:
    """Keywords Google Ads returned no row for → cache as null/0 so we don't re-query."""
    loc = settings["location_code"]
    lang = settings["language_code"]
    out: dict[str, dict] = {}
    for kw in keywords:
        key = cache_key(kw, loc, lang)
        if key in found_keys:
            continue
        out[key] = {
            "keyword": kw,
            "spell": None,
            "search_volume": None,
            "competition": None,
            "competition_index": None,
            "cpc": None,
            "low_top_of_page_bid": None,
            "high_top_of_page_bid": None,
            "monthly_searches": None,
            "location_code": loc,
            "language_code": lang,
            "fetched_at": fetched_at,
            "source": "dataforseo_google_ads",
            "no_data": True,
        }
    return out


# ---------------------------------------------------------------------------
# Aggregation / output
# ---------------------------------------------------------------------------

def _num(v: Any, default: float = 0.0) -> float:
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def aggregate_product(
    product_name: str,
    category: str,
    keywords: list[str],
    cache: dict,
    settings: dict,
) -> dict:
    loc = settings["location_code"]
    lang = settings["language_code"]
    entries = cache.get("entries") or {}

    volumes: list[tuple[str, float]] = []
    comps: list[float] = []
    cpcs: list[float] = []
    with_data = 0

    for kw in keywords:
        entry = entries.get(cache_key(kw, loc, lang)) or {}
        vol = entry.get("search_volume")
        if vol is not None:
            with_data += 1
            volumes.append((kw, float(vol)))
        ci = entry.get("competition_index")
        if ci is not None:
            comps.append(float(ci))
        cpc = entry.get("cpc")
        if cpc is not None:
            cpcs.append(float(cpc))

    if volumes:
        best_kw, best_vol = max(volumes, key=lambda x: x[1])
        vol_sum = sum(v for _, v in volumes)
        vol_avg = vol_sum / len(volumes)
    else:
        best_kw, best_vol, vol_sum, vol_avg = "", 0.0, 0.0, 0.0

    return {
        "product": product_name,
        "category": category,
        "search_volume": int(round(best_vol)),  # primary signal for scoring
        "search_volume_max": int(round(best_vol)),
        "search_volume_sum": int(round(vol_sum)),
        "search_volume_avg": round(vol_avg, 1),
        "search_volume_best_keyword": best_kw,
        "ads_competition_avg": round(sum(comps) / len(comps), 1) if comps else "",
        "cpc_avg": round(sum(cpcs) / len(cpcs), 2) if cpcs else "",
        "keywords_queried": len(keywords),
        "keywords_with_data": with_data,
    }


def write_product_csv(rows: list[dict], path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fields = [
        "product",
        "category",
        "search_volume",
        "search_volume_max",
        "search_volume_sum",
        "search_volume_avg",
        "search_volume_best_keyword",
        "ads_competition_avg",
        "cpc_avg",
        "keywords_queried",
        "keywords_with_data",
    ]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def write_keyword_csv(
    keywords: list[str],
    cache: dict,
    settings: dict,
    path: str,
) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    loc = settings["location_code"]
    lang = settings["language_code"]
    entries = cache.get("entries") or {}
    fields = [
        "keyword",
        "search_volume",
        "competition",
        "competition_index",
        "cpc",
        "low_top_of_page_bid",
        "high_top_of_page_bid",
        "spell",
        "fetched_at",
        "no_data",
    ]
    rows = []
    for kw in keywords:
        e = entries.get(cache_key(kw, loc, lang)) or {}
        rows.append(
            {
                "keyword": kw,
                "search_volume": e.get("search_volume", ""),
                "competition": e.get("competition", ""),
                "competition_index": e.get("competition_index", ""),
                "cpc": e.get("cpc", ""),
                "low_top_of_page_bid": e.get("low_top_of_page_bid", ""),
                "high_top_of_page_bid": e.get("high_top_of_page_bid", ""),
                "spell": e.get("spell", ""),
                "fetched_at": e.get("fetched_at", ""),
                "no_data": e.get("no_data", False),
            }
        )
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


# ---------------------------------------------------------------------------
# Estimate / main flow
# ---------------------------------------------------------------------------

def estimate(cfg: dict, force_refresh: bool, use_live: bool) -> None:
    settings = sv_settings(cfg)
    all_kws, by_product = collect_all_keywords(cfg)
    cache = load_cache(settings["cache_path"])
    fresh, need = partition_keywords(all_kws, cache, settings, force_refresh)

    n_tasks = 0 if not need else (len(need) + MAX_KEYWORDS_PER_TASK - 1) // MAX_KEYWORDS_PER_TASK
    unit = settings["cost_live"] if use_live else settings["cost_standard"]
    mode = "live" if use_live else "standard"
    ceiling = n_tasks * unit

    print("=== Search volume cost estimate (ceiling, not a quote) ===")
    print(f"products:              {len(by_product)}")
    print(f"unique keywords:       {len(all_kws)}")
    print(f"cache hits (fresh):    {len(fresh)}")
    print(f"need API fetch:        {len(need)}")
    print(f"queue mode:            {mode}")
    print(f"tasks required:        {n_tasks}  (≤{MAX_KEYWORDS_PER_TASK} kw/task)")
    print(f"@ ~${unit:.3f}/task:     ~${ceiling:.2f} this run")
    print(f"cache path:            {settings['cache_path']}")
    print(f"cache TTL:             {settings['cache_ttl_days']} days")
    print(f"location_code:         {settings['location_code']}")
    print(f"language_code:         {settings['language_code']}")
    if need[:15]:
        print("\nKeywords to fetch (sample):")
        for kw in need[:15]:
            print(f"  - {kw}")
        if len(need) > 15:
            print(f"  … +{len(need) - 15} more")
    if not need:
        print("\nAll keywords covered by fresh cache — this run would cost $0.")


def apply_api_result_to_cache(
    result: list[dict],
    keywords_requested: list[str],
    cache: dict,
    settings: dict,
) -> None:
    """Merge API rows into cache (including no-data markers) and save."""
    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    new_entries = result_rows_to_cache_entries(result, settings, fetched_at)
    cache.setdefault("entries", {}).update(new_entries)
    missing = mark_missing_as_zero(
        keywords_requested, set(new_entries.keys()), settings, fetched_at
    )
    cache["entries"].update(missing)
    save_cache(settings["cache_path"], cache)
    with_vol = sum(
        1 for e in new_entries.values() if e.get("search_volume") is not None
    )
    print(
        f"  cached {len(new_entries)} API rows "
        f"({with_vol} with search_volume, {len(new_entries) - with_vol} null) + "
        f"{len(missing)} no-data markers"
    )


def scan(
    config_path: str,
    out_products: str,
    out_keywords: str,
    *,
    force_refresh: bool = False,
    use_live: bool = False,
    cache_only: bool = False,
    poll_timeout: float | None = None,
    resume_task_id: str | None = None,
) -> None:
    cfg = load_config(config_path)
    settings = sv_settings(cfg)
    if poll_timeout is not None:
        settings["poll_timeout_s"] = poll_timeout

    if not settings["enabled"]:
        print("search_volume.enabled is false — writing empty product rows")
        rows = [
            {
                "product": p["name"],
                "category": p.get("category") or "",
                "search_volume": 0,
                "search_volume_max": 0,
                "search_volume_sum": 0,
                "search_volume_avg": 0,
                "search_volume_best_keyword": "",
                "ads_competition_avg": "",
                "cpc_avg": "",
                "keywords_queried": 0,
                "keywords_with_data": 0,
            }
            for p in (cfg.get("products") or [])
        ]
        write_product_csv(rows, out_products)
        write_keyword_csv([], {"entries": {}}, settings, out_keywords)
        return

    all_kws, by_product = collect_all_keywords(cfg)
    if not all_kws:
        print("ERROR: no keywords found in config products")
        sys.exit(1)

    cache = load_cache(settings["cache_path"])
    fresh, need = partition_keywords(all_kws, cache, settings, force_refresh)
    print(
        f"Keywords: {len(all_kws)} unique | cache hit {len(fresh)} | "
        f"fetch {len(need)} | mode={'live' if use_live else 'standard'}"
    )

    # Resume a previously posted Standard-queue task (no extra charge).
    if resume_task_id:
        login, password = get_credentials()
        print(f"  resuming task {resume_task_id} (GET only, $0)…")
        try:
            result = poll_task(resume_task_id, settings, login, password)
        except Exception as e:
            print(f"ERROR: resume failed: {e}")
            sys.exit(1)
        apply_api_result_to_cache(result, all_kws, cache, settings)
        need = []  # cache now populated

    if need:
        if cache_only:
            print(
                f"ERROR: --cache-only but {len(need)} keywords missing/stale. "
                f"Run without --cache-only or wait for TTL."
            )
            sys.exit(1)

        login, password = get_credentials()

        # Batch into ≤1000 keyword tasks
        for i in range(0, len(need), MAX_KEYWORDS_PER_TASK):
            batch = need[i : i + MAX_KEYWORDS_PER_TASK]
            print(f"  fetching batch {i // MAX_KEYWORDS_PER_TASK + 1}: {len(batch)} keywords")
            try:
                if use_live:
                    result = run_live(batch, settings, login, password)
                else:
                    task_id = post_standard_task(batch, settings, login, password)
                    print(
                        f"  (if interrupted, resume with: "
                        f"python3 search_volume_scan.py --resume-task {task_id})"
                    )
                    result = poll_task(task_id, settings, login, password)
            except Exception as e:
                print(f"ERROR: DataForSEO fetch failed: {e}")
                # Still write whatever we have from cache so pipeline can continue
                print("  writing partial results from cache; re-run to retry failed batch")
                break

            apply_api_result_to_cache(result, batch, cache, settings)
    elif not resume_task_id:
        print("  all keywords served from cache — $0 API cost this run")

    # Build product rows
    products = cfg.get("products") or []
    product_rows = []
    for p in products:
        name = p["name"]
        product_rows.append(
            aggregate_product(
                name,
                p.get("category") or "",
                by_product.get(name) or [],
                cache,
                settings,
            )
        )

    write_product_csv(product_rows, out_products)
    write_keyword_csv(all_kws, cache, settings, out_keywords)

    # Summary table
    print(f"\nWrote {len(product_rows)} products → {out_products}")
    print(f"Wrote {len(all_kws)} keywords → {out_keywords}")
    ranked = sorted(product_rows, key=lambda r: r["search_volume"], reverse=True)
    print("\n=== Search volume by product (max monthly) ===\n")
    for r in ranked:
        print(
            f"  {r['search_volume']:>6}  {r['product'][:50]:<50}  "
            f"({r['search_volume_best_keyword'] or '—'})"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fetch Google Ads search volume via DataForSEO."
    )
    parser.add_argument("--config", default="config/products.yaml")
    parser.add_argument("--out", default=DEFAULT_OUT_PRODUCTS)
    parser.add_argument("--out-keywords", default=DEFAULT_OUT_KEYWORDS)
    parser.add_argument(
        "--estimate",
        action="store_true",
        help="Show keyword plan and cost ceiling, then exit (no API charge).",
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Ignore cache TTL and re-query all keywords.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Use Live endpoint (faster, higher cost) instead of Standard queue.",
    )
    parser.add_argument(
        "--cache-only",
        action="store_true",
        help="Only use cache; error if any keyword is missing/stale.",
    )
    parser.add_argument(
        "--poll-timeout",
        type=float,
        default=None,
        help="Seconds to wait for standard-queue results (default from config).",
    )
    parser.add_argument(
        "--resume-task",
        default=None,
        metavar="TASK_ID",
        help=(
            "Fetch results for an already-posted Standard-queue task id "
            "(no extra charge). Use if a previous run posted then exited early."
        ),
    )
    args = parser.parse_args()

    cfg = load_config(args.config)
    settings = sv_settings(cfg)
    # Config can default queue to live; CLI --live always wins when set.
    use_live = args.live or settings["queue"] == "live"

    if args.estimate:
        estimate(cfg, force_refresh=args.force_refresh, use_live=use_live)
        sys.exit(0)

    scan(
        args.config,
        args.out,
        args.out_keywords,
        force_refresh=args.force_refresh,
        use_live=use_live,
        cache_only=args.cache_only,
        poll_timeout=args.poll_timeout,
        resume_task_id=args.resume_task,
    )
