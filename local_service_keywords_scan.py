#!/usr/bin/env python3
"""
local_service_keywords_scan.py
------------------------------
Discovers how people search for *local 3D printing services* in a city/metro
(default: Phoenix, AZ) using DataForSEO Google Ads Keywords For Keywords.

Unlike search_volume_scan.py (product demand), this answers:
  "What do people in {city} type when looking for a 3D print shop / service?"

API: DataForSEO Keywords Data → Google Ads → Keywords For Keywords
  Standard queue (default): task_post + poll task_get  (~$0.05–0.06 / task)
  Live (--live): single request, higher cost

One task accepts up to 20 seed keywords and returns related terms with
monthly search volume, competition, and CPC for the target location.

USAGE:
  python3 local_service_keywords_scan.py --estimate
  python3 local_service_keywords_scan.py
  python3 local_service_keywords_scan.py --city "Austin, TX"
  python3 local_service_keywords_scan.py --force
  python3 local_service_keywords_scan.py --top 15

SETUP:
  DATAFORSEO_LOGIN / DATAFORSEO_PASSWORD in .env (same as product volume scan)
  Optional: config/local_service.yaml

OUTPUT:
  out/local_service_keywords_{city_slug}.json
  out/local_service_keywords_{city_slug}.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
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
KFK_POST = f"{BASE_URL}/keywords_data/google_ads/keywords_for_keywords/task_post"
KFK_GET = f"{BASE_URL}/keywords_data/google_ads/keywords_for_keywords/task_get"
KFK_LIVE = f"{BASE_URL}/keywords_data/google_ads/keywords_for_keywords/live"

# Also pull exact volumes for seeds if missing from related set
SV_POST = f"{BASE_URL}/keywords_data/google_ads/search_volume/task_post"
SV_GET = f"{BASE_URL}/keywords_data/google_ads/search_volume/task_get"
SV_LIVE = f"{BASE_URL}/keywords_data/google_ads/search_volume/live"

PENDING_TASK_CODES = {20100, 40601, 40602}
MAX_SEEDS_PER_TASK = 20

DEFAULT_CONFIG = "config/local_service.yaml"
DEFAULT_CITY = "Phoenix, AZ"
DEFAULT_LOCATION_NAME = "Phoenix,Arizona,United States"
DEFAULT_SEEDS = [
    "3d printing service",
    "3d printing near me",
    "custom 3d printing",
    "3d print service",
    "prototype 3d printing",
    "small batch 3d printing",
    "3d printing for business",
    "3d printing phoenix",
    "additive manufacturing service",
    "rapid prototyping service",
    "3d printing company",
    "hire 3d printing",
    "3d printed parts service",
    "on demand 3d printing",
    "local 3d printing",
]

# Keep keywords that look like service / local print demand
RELEVANCE_INCLUDE = re.compile(
    r"\b("
    r"3d\s*print|3-?d\s*print|additive|prototyp|"
    r"fdm|sla|sls|resin\s*print|filament|"
    r"print\s*shop|print\s*service|printing\s*service|"
    r"custom\s*print|on[\s-]?demand\s*print|"
    r"small\s*batch|manufactur"
    r")\b",
    re.I,
)
RELEVANCE_EXCLUDE = re.compile(
    r"\b("
    r"t[\s-]?shirt|shirt|mug|business\s*card|flyer|brochure|"
    r"offset\s*print|screen\s*print|dtf|dtg|embroidery|"
    r"photo\s*print|canvas\s*print|poster\s*print|"
    r"book\s*print|newspaper|magazine|"
    r"lego|minecraft|fortnite|"
    r"filament\s*near\s*me|printer\s*filament"  # retail consumables, not services
    r")\b",
    re.I,
)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_yaml(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    with p.open() as f:
        return yaml.safe_load(f) or {}


def city_slug(city: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (city or "city").lower()).strip("_")
    return s or "city"


def city_to_location_name(city: str) -> str:
    """
    Best-effort: 'Phoenix, AZ' → 'Phoenix,Arizona,United States'
    'Austin, TX' → 'Austin,Texas,United States'
    """
    city = (city or "").strip()
    if not city:
        return DEFAULT_LOCATION_NAME
    # Already full DFS form
    if city.count(",") >= 2 or "United States" in city:
        return city

    us_states = {
        "al": "Alabama", "ak": "Alaska", "az": "Arizona", "ar": "Arkansas",
        "ca": "California", "co": "Colorado", "ct": "Connecticut", "de": "Delaware",
        "fl": "Florida", "ga": "Georgia", "hi": "Hawaii", "id": "Idaho",
        "il": "Illinois", "in": "Indiana", "ia": "Iowa", "ks": "Kansas",
        "ky": "Kentucky", "la": "Louisiana", "me": "Maine", "md": "Maryland",
        "ma": "Massachusetts", "mi": "Michigan", "mn": "Minnesota", "ms": "Mississippi",
        "mo": "Missouri", "mt": "Montana", "ne": "Nebraska", "nv": "Nevada",
        "nh": "New Hampshire", "nj": "New Jersey", "nm": "New Mexico", "ny": "New York",
        "nc": "North Carolina", "nd": "North Dakota", "oh": "Ohio", "ok": "Oklahoma",
        "or": "Oregon", "pa": "Pennsylvania", "ri": "Rhode Island", "sc": "South Carolina",
        "sd": "South Dakota", "tn": "Tennessee", "tx": "Texas", "ut": "Utah",
        "vt": "Vermont", "va": "Virginia", "wa": "Washington", "wv": "West Virginia",
        "wi": "Wisconsin", "wy": "Wyoming", "dc": "District of Columbia",
    }
    parts = [p.strip() for p in city.split(",")]
    if len(parts) >= 2:
        place, st = parts[0], parts[1].lower().replace(".", "")
        state = us_states.get(st, parts[1].title())
        return f"{place},{state},United States"
    return f"{city},United States"


def location_short_tokens(city: str) -> list[str]:
    """Tokens for auto seed variants: ['phoenix', 'phoenix az']."""
    city = (city or "").strip()
    parts = [p.strip() for p in city.split(",") if p.strip()]
    if not parts:
        return []
    place = parts[0].lower()
    out = [place]
    if len(parts) >= 2:
        st = parts[1].lower().replace(".", "")
        out.append(f"{place} {st}")
    return out


def resolve_settings(cfg: dict, city_override: str | None) -> dict:
    s = (cfg.get("local_service") or cfg) if cfg else {}
    city = (city_override or s.get("city") or DEFAULT_CITY).strip()
    loc_name = s.get("location_name")
    loc_code = s.get("location_code")
    if city_override:
        # CLI city wins: rebuild location_name unless user set code only in config
        # and city matches config — always rebuild from CLI city for predictability
        loc_name = city_to_location_name(city)
        loc_code = None

    if not loc_name and not loc_code:
        loc_name = city_to_location_name(city)

    seeds = list(s.get("seed_keywords") or DEFAULT_SEEDS)
    return {
        "city": city,
        "city_slug": city_slug(city),
        "location_name": loc_name,
        "location_code": int(loc_code) if loc_code not in (None, "", "null") else None,
        "language_code": str(s.get("language_code") or "en"),
        "queue": str(s.get("queue") or "standard").lower(),
        "cache_ttl_days": int(s.get("cache_ttl_days") or 14),
        "cache_dir": str(s.get("cache_dir") or "cache/local_service_keywords"),
        "poll_interval_s": float(s.get("poll_interval_s") or 15.0),
        "poll_timeout_s": float(s.get("poll_timeout_s") or 3600.0),
        "search_partners": bool(s.get("search_partners", False)),
        "top_n": int(s.get("top_n") or 20),
        "max_related": int(s.get("max_related") or 200),
        "cost_standard": float(s.get("cost_standard") or 0.05),
        "cost_live": float(s.get("cost_live") or 0.075),
        "seed_keywords": seeds,
    }


def get_credentials() -> tuple[str, str]:
    login = (os.environ.get("DATAFORSEO_LOGIN") or "").strip()
    password = (os.environ.get("DATAFORSEO_PASSWORD") or "").strip()
    if not login or not password:
        print(
            "ERROR: set DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD in .env\n"
            "  Get them from https://app.dataforseo.com/api-access\n"
            "  Same credentials as search_volume_scan.py"
        )
        sys.exit(1)
    return login, password


# ---------------------------------------------------------------------------
# Seeds
# ---------------------------------------------------------------------------

def normalize_keyword(kw: str) -> str | None:
    if not kw:
        return None
    k = " ".join(str(kw).strip().lower().split())
    if not k:
        return None
    cleaned = "".join(ch if ch.isalnum() or ch in " -'&./" else " " for ch in k)
    cleaned = " ".join(cleaned.split())
    if len(cleaned) > 80:
        cleaned = cleaned[:80].rsplit(" ", 1)[0]
    return cleaned or None


def build_seed_list(settings: dict) -> list[str]:
    """Base seeds + location variants, capped at API max 20."""
    seeds: list[str] = []
    seen: set[str] = set()

    def add(kw: str) -> None:
        n = normalize_keyword(kw)
        if n and n not in seen and len(seeds) < MAX_SEEDS_PER_TASK:
            seen.add(n)
            seeds.append(n)

    for kw in settings["seed_keywords"]:
        add(kw)

    for tok in location_short_tokens(settings["city"]):
        for base in (
            "3d printing service",
            "3d printing",
            "3d print service",
            "custom 3d printing",
            "prototype 3d printing",
        ):
            add(f"{base} {tok}")
            add(f"{tok} 3d printing")

    return seeds


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def cache_path(settings: dict) -> Path:
    return Path(settings["cache_dir"]) / f"{settings['city_slug']}.json"


def load_cache(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        with path.open() as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"  [warn] cache unreadable ({e})")
        return None


def cache_is_fresh(cache: dict, ttl_days: int) -> bool:
    fetched = cache.get("fetched_at")
    if not fetched:
        return False
    try:
        ts = datetime.fromisoformat(fetched.replace("Z", "+00:00"))
    except ValueError:
        return False
    age = datetime.now(timezone.utc) - ts.astimezone(timezone.utc)
    return age.total_seconds() < ttl_days * 86400


def save_cache(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w") as f:
        json.dump(payload, f, indent=2)
    tmp.replace(path)


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
                return resp.json()
            except ValueError:
                raise RuntimeError(
                    f"non-JSON HTTP {resp.status_code}: {resp.text[:200]}"
                )
        except requests.RequestException as e:
            last_err = e
            time.sleep(min(60.0, (2**attempt) * 3.0))
    raise RuntimeError(f"DataForSEO request failed: {last_err}")


def location_payload(settings: dict) -> dict[str, Any]:
    task: dict[str, Any] = {
        "language_code": settings["language_code"],
        "search_partners": settings["search_partners"],
    }
    if settings.get("location_code") is not None:
        task["location_code"] = settings["location_code"]
    elif settings.get("location_name"):
        task["location_name"] = settings["location_name"]
    return task


def post_task(
    endpoint: str,
    keywords: list[str],
    settings: dict,
    login: str,
    password: str,
    *,
    sort_by: str | None = None,
) -> str:
    task = {
        **location_payload(settings),
        "keywords": keywords,
    }
    if sort_by:
        task["sort_by"] = sort_by
    resp = api_request("POST", endpoint, login, password, json_body=[task])
    if resp.get("status_code") != 20000:
        raise RuntimeError(
            f"task_post failed: {resp.get('status_code')} {resp.get('status_message')}"
        )
    tasks = resp.get("tasks") or []
    if not tasks:
        raise RuntimeError("task_post returned no tasks")
    t0 = tasks[0]
    if t0.get("status_code") not in (20000, 20100):
        raise RuntimeError(
            f"task create error: {t0.get('status_code')} {t0.get('status_message')}"
        )
    tid = t0.get("id")
    if not tid:
        raise RuntimeError("missing task id")
    cost = t0.get("cost") or resp.get("cost")
    print(f"  posted task {tid} (cost reported: ${cost})")
    return tid


def poll_task(
    get_base: str,
    task_id: str,
    settings: dict,
    login: str,
    password: str,
) -> list[dict]:
    deadline = time.time() + settings["poll_timeout_s"]
    interval = settings["poll_interval_s"]
    url = f"{get_base}/{task_id}"
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        resp = api_request("GET", url, login, password)
        if resp.get("status_code") != 20000:
            print(
                f"  [warn] envelope {resp.get('status_code')} "
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
        if code == 20000:
            result = task.get("result")
            if result is None:
                print(f"  [warn] ready but null result; re-poll ({msg})")
                time.sleep(interval)
                continue
            print(f"  task ready after {attempt} poll(s); {len(result)} rows")
            return result
        if code in PENDING_TASK_CODES or 10000 <= code < 40000:
            if attempt == 1 or attempt % 4 == 0:
                print(f"  waiting… status={code} {msg} (poll {attempt})")
            time.sleep(interval)
            continue
        raise RuntimeError(f"task failed: {code} {msg}")
    raise TimeoutError(
        f"task {task_id} not ready within {settings['poll_timeout_s']:.0f}s"
    )


def run_live(
    endpoint: str,
    keywords: list[str],
    settings: dict,
    login: str,
    password: str,
    *,
    sort_by: str | None = None,
) -> list[dict]:
    task = {
        **location_payload(settings),
        "keywords": keywords,
    }
    if sort_by:
        task["sort_by"] = sort_by
    resp = api_request(
        "POST", endpoint, login, password, json_body=[task], timeout=120.0
    )
    if resp.get("status_code") != 20000:
        raise RuntimeError(
            f"live failed: {resp.get('status_code')} {resp.get('status_message')}"
        )
    tasks = resp.get("tasks") or []
    if not tasks:
        raise RuntimeError("live returned no tasks")
    t0 = tasks[0]
    if t0.get("status_code") != 20000:
        raise RuntimeError(
            f"live task error: {t0.get('status_code')} {t0.get('status_message')}"
        )
    cost = t0.get("cost") or resp.get("cost")
    result = t0.get("result") or []
    print(f"  live complete (cost reported: ${cost}); {len(result)} rows")
    return result


# ---------------------------------------------------------------------------
# Ranking / filter
# ---------------------------------------------------------------------------

def row_from_api(item: dict, *, source: str) -> dict | None:
    kw = normalize_keyword(item.get("keyword") or "")
    if not kw:
        return None
    vol = item.get("search_volume")
    try:
        vol_i = int(vol) if vol is not None else None
    except (TypeError, ValueError):
        vol_i = None
    return {
        "keyword": kw,
        "search_volume": vol_i,
        "competition": item.get("competition"),
        "competition_index": item.get("competition_index"),
        "cpc": item.get("cpc"),
        "low_top_of_page_bid": item.get("low_top_of_page_bid"),
        "high_top_of_page_bid": item.get("high_top_of_page_bid"),
        "source": source,
    }


def is_relevant(keyword: str) -> bool:
    if RELEVANCE_EXCLUDE.search(keyword):
        return False
    return bool(RELEVANCE_INCLUDE.search(keyword))


def merge_keyword_rows(rows: list[dict]) -> list[dict]:
    by_kw: dict[str, dict] = {}
    for r in rows:
        kw = r["keyword"]
        prev = by_kw.get(kw)
        if not prev:
            by_kw[kw] = r
            continue
        # Prefer row with volume data
        if prev.get("search_volume") is None and r.get("search_volume") is not None:
            by_kw[kw] = r
    return list(by_kw.values())


def rank_keywords(rows: list[dict], top_n: int, max_related: int) -> list[dict]:
    relevant = [r for r in rows if is_relevant(r["keyword"])]
    # Prefer volume desc; null volumes last
    relevant.sort(
        key=lambda r: (
            r.get("search_volume") is not None,
            r.get("search_volume") or 0,
        ),
        reverse=True,
    )
    # Cap intermediate noise
    relevant = relevant[: max(max_related, top_n)]
    ranked = []
    for i, r in enumerate(relevant[:top_n], 1):
        out = dict(r)
        out["rank"] = i
        ranked.append(out)
    return ranked


# ---------------------------------------------------------------------------
# Estimate / main
# ---------------------------------------------------------------------------

def estimate(settings: dict, use_live: bool, force: bool) -> None:
    seeds = build_seed_list(settings)
    path = cache_path(settings)
    cache = load_cache(path)
    fresh = bool(cache and cache_is_fresh(cache, settings["cache_ttl_days"]) and not force)
    unit = settings["cost_live"] if use_live else settings["cost_standard"]
    # 1 keywords_for_keywords task + optional 1 search_volume task for seeds
    n_tasks = 0 if fresh else 2
    print("=== Local service keywords — cost estimate ===")
    print(f"city:                 {settings['city']}")
    print(f"location_name:        {settings.get('location_name')}")
    print(f"location_code:        {settings.get('location_code')}")
    print(f"seed keywords:        {len(seeds)} (API max {MAX_SEEDS_PER_TASK})")
    print(f"queue:                {'live' if use_live else 'standard'}")
    print(f"cache:                {path}")
    print(f"cache fresh:          {fresh} (TTL {settings['cache_ttl_days']}d)")
    print(f"tasks if cold:        ~{n_tasks}  (related + seed volume)")
    print(f"@ ~${unit:.3f}/task:    ~${n_tasks * unit:.2f} this run")
    print("\nSeeds to send:")
    for s in seeds:
        print(f"  - {s}")
    if fresh:
        print("\nCache is fresh — this run would cost $0 (use --force to refresh).")


def write_outputs(
    settings: dict,
    ranked: list[dict],
    *,
    seeds: list[str],
    all_rows: list[dict],
    fetched_at: str,
    from_cache: bool,
) -> tuple[Path, Path]:
    slug = settings["city_slug"]
    out_json = Path(f"out/local_service_keywords_{slug}.json")
    out_csv = Path(f"out/local_service_keywords_{slug}.csv")
    out_json.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "city": settings["city"],
        "city_slug": slug,
        "location_name": settings.get("location_name"),
        "location_code": settings.get("location_code"),
        "language_code": settings["language_code"],
        "fetched_at": fetched_at,
        "from_cache": from_cache,
        "seed_keywords": seeds,
        "top_n": settings["top_n"],
        "keywords": ranked,
        "all_keywords_count": len(all_rows),
        "notes": (
            "Ranked by monthly search volume for the target location. "
            "Use for local 3D printing *service* demand research."
        ),
    }
    with out_json.open("w") as f:
        json.dump(payload, f, indent=2)

    fields = [
        "rank",
        "keyword",
        "search_volume",
        "competition",
        "competition_index",
        "cpc",
        "low_top_of_page_bid",
        "high_top_of_page_bid",
        "source",
        "city",
        "location_name",
        "fetched_at",
    ]
    with out_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in ranked:
            row = dict(r)
            row["city"] = settings["city"]
            row["location_name"] = settings.get("location_name") or ""
            row["fetched_at"] = fetched_at
            w.writerow(row)

    return out_json, out_csv


def scan(
    config_path: str,
    *,
    city: str | None = None,
    force: bool = False,
    use_live: bool = False,
    top_n: int | None = None,
) -> None:
    cfg = load_yaml(config_path)
    settings = resolve_settings(cfg, city)
    if top_n is not None:
        settings["top_n"] = top_n
    if use_live:
        settings["queue"] = "live"

    seeds = build_seed_list(settings)
    path = cache_path(settings)

    print(f"City:     {settings['city']}")
    print(f"Location: {settings.get('location_name') or settings.get('location_code')}")
    print(f"Seeds:    {len(seeds)}")

    cache = load_cache(path)
    if cache and cache_is_fresh(cache, settings["cache_ttl_days"]) and not force:
        print(f"  cache hit → {path} (use --force to refresh)")
        ranked = cache.get("keywords") or []
        all_rows = cache.get("all_keywords") or ranked
        fetched_at = cache.get("fetched_at") or ""
        out_json, out_csv = write_outputs(
            settings,
            ranked,
            seeds=cache.get("seed_keywords") or seeds,
            all_rows=all_rows,
            fetched_at=fetched_at,
            from_cache=True,
        )
        _print_table(ranked, settings["city"])
        print(f"\nWrote {out_json} and {out_csv}")
        return

    try:
        login, password = get_credentials()
    except SystemExit:
        raise

    live = settings["queue"] == "live"
    all_api_rows: list[dict] = []

    # 1) Keywords for keywords (related + metrics)
    print("  [1/2] keywords_for_keywords (related + volumes)…")
    try:
        if live:
            raw = run_live(
                KFK_LIVE,
                seeds,
                settings,
                login,
                password,
                sort_by="search_volume",
            )
        else:
            tid = post_task(
                KFK_POST,
                seeds,
                settings,
                login,
                password,
                sort_by="search_volume",
            )
            print(
                f"  (resume if interrupted: re-run after task completes; "
                f"task id {tid})"
            )
            raw = poll_task(KFK_GET, tid, settings, login, password)
        for item in raw:
            row = row_from_api(item, source="keywords_for_keywords")
            if row:
                all_api_rows.append(row)
    except Exception as e:
        print(f"ERROR: keywords_for_keywords failed: {e}")
        sys.exit(1)

    # 2) Search volume for seeds (guarantees seed metrics even if not in related)
    print("  [2/2] search_volume (seed keywords)…")
    try:
        if live:
            raw = run_live(SV_LIVE, seeds, settings, login, password)
        else:
            tid = post_task(SV_POST, seeds, settings, login, password)
            raw = poll_task(SV_GET, tid, settings, login, password)
        for item in raw:
            row = row_from_api(item, source="search_volume_seed")
            if row:
                all_api_rows.append(row)
    except Exception as e:
        print(f"  [warn] seed search_volume failed ({e}); continuing with related only")

    merged = merge_keyword_rows(all_api_rows)
    ranked = rank_keywords(merged, settings["top_n"], settings["max_related"])
    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    cache_payload = {
        "city": settings["city"],
        "location_name": settings.get("location_name"),
        "location_code": settings.get("location_code"),
        "fetched_at": fetched_at,
        "seed_keywords": seeds,
        "keywords": ranked,
        "all_keywords": merged,
    }
    save_cache(path, cache_payload)
    print(f"  cached → {path}")

    out_json, out_csv = write_outputs(
        settings,
        ranked,
        seeds=seeds,
        all_rows=merged,
        fetched_at=fetched_at,
        from_cache=False,
    )
    _print_table(ranked, settings["city"])
    print(f"\nWrote {out_json} and {out_csv}")
    print(
        f"\nAnswer: top ways people near {settings['city']} search for "
        f"3D printing services (by monthly volume):"
    )
    for r in ranked[:10]:
        vol = r.get("search_volume")
        vol_s = f"{vol:,}" if vol is not None else "n/a"
        print(f"  {r['rank']:>2}. {vol_s:>8}  {r['keyword']}")


def _print_table(ranked: list[dict], city: str) -> None:
    print(f"\n=== Local 3D printing service keywords — {city} ===\n")
    print(f"{'rank':>4}  {'volume':>8}  {'comp':>6}  {'cpc':>6}  keyword")
    for r in ranked:
        vol = r.get("search_volume")
        vol_s = f"{vol:,}" if vol is not None else "—"
        comp = r.get("competition_index")
        comp_s = str(comp) if comp is not None else (r.get("competition") or "—")
        cpc = r.get("cpc")
        cpc_s = f"{cpc:.2f}" if isinstance(cpc, (int, float)) else "—"
        print(f"{r.get('rank', 0):>4}  {vol_s:>8}  {str(comp_s):>6}  {cpc_s:>6}  {r['keyword']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Local 3D printing service keyword research via DataForSEO."
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument(
        "--city",
        default=None,
        help='Target city, e.g. "Phoenix, AZ" or "Austin, TX"',
    )
    parser.add_argument(
        "--estimate",
        action="store_true",
        help="Show plan + cost ceiling; no API charge",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ignore cache TTL and re-query",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Use Live endpoints (faster, higher cost)",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=None,
        help="How many ranked keywords to keep (default from config, usually 20)",
    )
    args = parser.parse_args()

    cfg = load_yaml(args.config)
    settings = resolve_settings(cfg, args.city)
    if args.top is not None:
        settings["top_n"] = args.top
    use_live = args.live or settings["queue"] == "live"

    if args.estimate:
        estimate(settings, use_live=use_live, force=args.force)
        sys.exit(0)

    scan(
        args.config,
        city=args.city,
        force=args.force,
        use_live=use_live,
        top_n=args.top,
    )
