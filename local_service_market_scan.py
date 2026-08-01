#!/usr/bin/env python3
"""
local_service_market_scan.py
----------------------------
Deeper local market research for 3D printing *services* in a city/metro
(default: Phoenix, AZ).

Builds on local_service_keywords_scan.py and adds:
  1) Related keywords tagged by intent
  2) People Also Ask questions (DataForSEO Google Organic SERP)
  3) Lightweight local competitor snapshot (DataForSEO Google Maps SERP)
  4) Human-readable market summary

USAGE:
  python3 local_service_market_scan.py --estimate
  python3 local_service_market_scan.py
  python3 local_service_market_scan.py --city "Austin, TX"
  python3 local_service_market_scan.py --force
  python3 local_service_market_scan.py --skip-serp --skip-maps   # keywords only
  python3 local_service_market_scan.py --paa-limit 3

SETUP:
  DATAFORSEO_LOGIN / DATAFORSEO_PASSWORD in .env
  config/local_service.yaml

OUTPUT:
  out/local_service_market_{city}.json
  out/local_service_market_{city}.md
"""
from __future__ import annotations

import argparse
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

# Reuse city/config/credential helpers from the keyword scanner
from local_service_keywords_scan import (  # noqa: E402
    DEFAULT_CONFIG,
    api_request,
    cache_is_fresh,
    cache_path,
    get_credentials,
    load_cache,
    load_yaml,
    resolve_settings,
)

BASE_URL = "https://api.dataforseo.com/v3"
SERP_ORGANIC_LIVE = f"{BASE_URL}/serp/google/organic/live/advanced"
SERP_MAPS_LIVE = f"{BASE_URL}/serp/google/maps/live/advanced"

# Estimate-only unit costs (update if DataForSEO pricing changes)
COST_SERP_ORGANIC = 0.002
COST_SERP_MAPS = 0.002
COST_KEYWORD_TASK = 0.05

DEFAULT_PAA_LIMIT = 4
DEFAULT_MAPS_DEPTH = 20
DEFAULT_MARKET_CACHE_DIR = "cache/local_service_market"


# ---------------------------------------------------------------------------
# Intent tagging
# ---------------------------------------------------------------------------

INTENT_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("near_me", re.compile(r"\b(near\s*me|nearby|local|close\s*to)\b", re.I)),
    ("online", re.compile(r"\b(online|mail\s*order|upload|instant\s*quote)\b", re.I)),
    (
        "process",
        re.compile(
            r"\b(fdm|sla|sls|mjf|dmls|resin|fused\s*deposition|stereolith|"
            r"selective\s*laser|multi\s*jet)\b",
            re.I,
        ),
    ),
    (
        "material",
        re.compile(
            r"\b(metal|nylon|abs|pla|petg|tpu|carbon|aluminum|titanium|"
            r"polycarbonate|resin)\b",
            re.I,
        ),
    ),
    (
        "prototype",
        re.compile(r"\b(prototype|prototyping|rapid\s*proto|concept\s*model)\b", re.I),
    ),
    (
        "production",
        re.compile(
            r"\b(production|small\s*batch|batch|manufactur|end[\s-]?use|"
            r"bridge\s*production)\b",
            re.I,
        ),
    ),
    (
        "business",
        re.compile(r"\b(business|company|industrial|b2b|commercial)\b", re.I),
    ),
    (
        "price",
        re.compile(r"\b(cheap|affordable|cost|price|pricing|quote)\b", re.I),
    ),
]


def tag_intent(keyword: str) -> list[str]:
    tags = [name for name, pat in INTENT_RULES if pat.search(keyword or "")]
    # Local branded if city token appears
    if re.search(r"\b(phoenix|scottsdale|tempe|mesa|chandler|gilbert)\b", keyword or "", re.I):
        if "local_branded" not in tags:
            tags.append("local_branded")
    if not tags:
        tags = ["general_service"]
    return tags


def enrich_keywords_with_intent(keywords: list[dict]) -> list[dict]:
    out = []
    for kw in keywords:
        row = dict(kw)
        row["intents"] = tag_intent(row.get("keyword") or "")
        out.append(row)
    return out


def group_by_intent(keywords: list[dict], per_intent: int = 12) -> dict[str, list[dict]]:
    buckets: dict[str, list[dict]] = {}
    for kw in keywords:
        for intent in kw.get("intents") or ["general_service"]:
            buckets.setdefault(intent, []).append(
                {
                    "keyword": kw.get("keyword"),
                    "search_volume": kw.get("search_volume"),
                    "competition_index": kw.get("competition_index"),
                    "cpc": kw.get("cpc"),
                    "rank": kw.get("rank"),
                }
            )
    # Sort each bucket by volume
    for intent, rows in buckets.items():
        rows.sort(
            key=lambda r: (
                r.get("search_volume") is not None,
                r.get("search_volume") or 0,
            ),
            reverse=True,
        )
        buckets[intent] = rows[:per_intent]
    return buckets


# ---------------------------------------------------------------------------
# Keyword data load / ensure
# ---------------------------------------------------------------------------

def load_keyword_report(settings: dict) -> dict | None:
    """Prefer out/ JSON, then keyword cache."""
    slug = settings["city_slug"]
    out_path = Path(f"out/local_service_keywords_{slug}.json")
    if out_path.exists():
        try:
            with out_path.open() as f:
                data = json.load(f)
            if data.get("keywords"):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    cache = load_cache(cache_path(settings))
    if cache and cache.get("keywords"):
        return {
            "city": settings["city"],
            "location_name": settings.get("location_name"),
            "keywords": cache.get("keywords") or [],
            "all_keywords": cache.get("all_keywords") or cache.get("keywords") or [],
            "seed_keywords": cache.get("seed_keywords") or [],
            "fetched_at": cache.get("fetched_at"),
            "from_cache": True,
        }
    return None


def ensure_keywords(
    settings: dict,
    *,
    force: bool,
    config_path: str,
) -> dict:
    """Return keyword report; run keyword scanner if missing/stale and force."""
    existing = load_keyword_report(settings)
    cache = load_cache(cache_path(settings))
    fresh = bool(cache and cache_is_fresh(cache, settings["cache_ttl_days"]))

    if existing and fresh and not force:
        print("  keywords: using cached/out keyword report")
        return existing

    if existing and not force:
        print("  keywords: using existing out/ report (cache may be aging)")
        return existing

    print("  keywords: running local_service_keywords_scan…")
    # Import and call scan() — may charge DataForSEO
    from local_service_keywords_scan import scan as keyword_scan

    keyword_scan(
        config_path,
        city=settings["city"],
        force=force,
        use_live=settings.get("queue") == "live",
    )
    report = load_keyword_report(settings)
    if not report:
        raise RuntimeError("keyword scan finished but no report found")
    return report


# ---------------------------------------------------------------------------
# SERP: People Also Ask
# ---------------------------------------------------------------------------

def serp_location_payload(settings: dict) -> dict[str, Any]:
    task: dict[str, Any] = {
        "language_code": settings.get("language_code") or "en",
    }
    if settings.get("location_code") is not None:
        task["location_code"] = settings["location_code"]
    else:
        task["location_name"] = (
            settings.get("location_name") or "Phoenix,Arizona,United States"
        )
    return task


def fetch_organic_serp(
    keyword: str,
    settings: dict,
    login: str,
    password: str,
    *,
    depth: int = 10,
) -> dict:
    task = {
        **serp_location_payload(settings),
        "keyword": keyword,
        "depth": depth,
        "device": "desktop",
        "people_also_ask_click_depth": 2,  # small extra for more questions
    }
    resp = api_request(
        "POST",
        SERP_ORGANIC_LIVE,
        login,
        password,
        json_body=[task],
        timeout=120.0,
    )
    if resp.get("status_code") != 20000:
        raise RuntimeError(
            f"organic SERP failed: {resp.get('status_code')} {resp.get('status_message')}"
        )
    tasks = resp.get("tasks") or []
    if not tasks:
        raise RuntimeError("organic SERP returned no tasks")
    t0 = tasks[0]
    if t0.get("status_code") != 20000:
        raise RuntimeError(
            f"organic task error: {t0.get('status_code')} {t0.get('status_message')}"
        )
    cost = t0.get("cost") or resp.get("cost")
    result = (t0.get("result") or [None])[0] or {}
    return {"cost": cost, "result": result, "raw_status": t0.get("status_message")}


def extract_paa(result: dict) -> list[dict]:
    """Pull People Also Ask questions from organic advanced result."""
    questions: list[dict] = []
    seen: set[str] = set()
    items = result.get("items") or []

    def add_q(title: str, expanded: str | None = None) -> None:
        t = (title or "").strip()
        if not t or t.lower() in seen:
            return
        seen.add(t.lower())
        questions.append(
            {
                "question": t,
                "snippet": (expanded or "").strip() or None,
            }
        )

    for item in items:
        itype = (item.get("type") or "").lower()
        if itype == "people_also_ask":
            for el in item.get("items") or []:
                # people_also_ask_element
                title = el.get("title") or el.get("question")
                # expanded answer may be nested
                expanded = None
                for nested in el.get("expanded_element") or []:
                    if isinstance(nested, dict):
                        expanded = (
                            nested.get("description")
                            or nested.get("title")
                            or expanded
                        )
                add_q(title, expanded)
        # Some responses nest differently
        if itype == "people_also_ask_element":
            add_q(item.get("title"), item.get("description"))

    return questions


def collect_people_also_ask(
    keywords: list[dict],
    settings: dict,
    login: str,
    password: str,
    *,
    paa_limit: int,
) -> tuple[list[dict], float]:
    """SERP PAA for top service-intent keywords."""
    # Prefer high-volume *service* phrases over pure process terms
    preferred = []
    for kw in keywords:
        text = (kw.get("keyword") or "").lower()
        score = kw.get("search_volume") or 0
        if any(
            t in text
            for t in (
                "service",
                "shop",
                "near me",
                "company",
                "prototype",
                "business",
            )
        ):
            score += 1000
        preferred.append((score, kw))
    preferred.sort(key=lambda x: x[0], reverse=True)

    chosen: list[str] = []
    for _, kw in preferred:
        k = kw.get("keyword")
        if k and k not in chosen:
            chosen.append(k)
        if len(chosen) >= paa_limit:
            break

    # Always include core phrases if present
    for core in ("3d printing service", "3d print service", "fdm 3d printing"):
        if core not in chosen and any(
            (k.get("keyword") or "").lower() == core for k in keywords
        ):
            if len(chosen) < paa_limit + 1:
                chosen.append(core)

    results = []
    total_cost = 0.0
    for i, keyword in enumerate(chosen[:paa_limit]):
        print(f"  PAA SERP [{i + 1}/{min(paa_limit, len(chosen))}]: {keyword!r}")
        try:
            payload = fetch_organic_serp(keyword, settings, login, password)
            total_cost += float(payload.get("cost") or 0)
            qs = extract_paa(payload.get("result") or {})
            # Also harvest local_pack names as soft competitor signal
            local_pack = []
            for item in (payload.get("result") or {}).get("items") or []:
                if (item.get("type") or "").lower() == "local_pack":
                    for el in item.get("items") or [item]:
                        if el.get("title"):
                            local_pack.append(
                                {
                                    "name": el.get("title"),
                                    "rating": (el.get("rating") or {}).get("value")
                                    if isinstance(el.get("rating"), dict)
                                    else el.get("rating"),
                                    "reviews": (el.get("rating") or {}).get(
                                        "votes_count"
                                    )
                                    if isinstance(el.get("rating"), dict)
                                    else None,
                                    "snippet": el.get("description")
                                    or el.get("snippet"),
                                }
                            )
            results.append(
                {
                    "parent_keyword": keyword,
                    "questions": qs,
                    "local_pack_preview": local_pack[:5],
                    "question_count": len(qs),
                }
            )
            print(f"    → {len(qs)} questions")
        except Exception as e:
            print(f"    [warn] PAA failed for {keyword!r}: {e}")
            results.append(
                {
                    "parent_keyword": keyword,
                    "questions": [],
                    "local_pack_preview": [],
                    "question_count": 0,
                    "error": str(e),
                }
            )
        time.sleep(0.5)
    return results, total_cost


# ---------------------------------------------------------------------------
# Maps competitors
# ---------------------------------------------------------------------------

def fetch_maps_serp(
    keyword: str,
    settings: dict,
    login: str,
    password: str,
    *,
    depth: int = 20,
) -> dict:
    task = {
        **serp_location_payload(settings),
        "keyword": keyword,
        "depth": min(depth, 100),
        "device": "desktop",
        "search_places": False,  # better for local-intent queries
    }
    resp = api_request(
        "POST",
        SERP_MAPS_LIVE,
        login,
        password,
        json_body=[task],
        timeout=120.0,
    )
    if resp.get("status_code") != 20000:
        raise RuntimeError(
            f"maps SERP failed: {resp.get('status_code')} {resp.get('status_message')}"
        )
    tasks = resp.get("tasks") or []
    if not tasks:
        raise RuntimeError("maps SERP returned no tasks")
    t0 = tasks[0]
    if t0.get("status_code") != 20000:
        raise RuntimeError(
            f"maps task error: {t0.get('status_code')} {t0.get('status_message')}"
        )
    cost = t0.get("cost") or resp.get("cost")
    result = (t0.get("result") or [None])[0] or {}
    return {"cost": cost, "result": result}


def extract_maps_competitors(result: dict, limit: int = 15) -> list[dict]:
    competitors = []
    for item in result.get("items") or []:
        if (item.get("type") or "").lower() not in ("maps_search", "maps_paid_item"):
            # Some payloads omit type or use slightly different labels
            if not item.get("title"):
                continue
        rating = item.get("rating") or {}
        if not isinstance(rating, dict):
            rating = {}
        competitors.append(
            {
                "name": item.get("title") or item.get("original_title"),
                "rating": rating.get("value"),
                "review_count": rating.get("votes_count"),
                "address": item.get("address") or item.get("snippet"),
                "snippet": item.get("snippet"),
                "category": item.get("category"),
                "phone": item.get("phone"),
                "url": item.get("url") or item.get("contact_url"),
                "place_id": item.get("place_id"),
                "is_claimed": item.get("is_claimed"),
            }
        )
        if len(competitors) >= limit:
            break
    return competitors


def collect_competitors(
    settings: dict,
    login: str,
    password: str,
    *,
    depth: int,
) -> tuple[list[dict], float, str]:
    city = settings["city"]
    # Query designed to surface local print services
    query = f"3d printing service {city.split(',')[0]}"
    print(f"  Maps SERP: {query!r}")
    try:
        payload = fetch_maps_serp(query, settings, login, password, depth=depth)
        cost = float(payload.get("cost") or 0)
        comps = extract_maps_competitors(payload.get("result") or {}, limit=depth)
        print(f"    → {len(comps)} businesses (cost ${cost})")
        return comps, cost, query
    except Exception as e:
        print(f"    [warn] maps failed: {e}")
        return [], 0.0, query


# ---------------------------------------------------------------------------
# Summary / report
# ---------------------------------------------------------------------------

def build_summary(
    settings: dict,
    keywords: list[dict],
    by_intent: dict[str, list[dict]],
    paa: list[dict],
    competitors: list[dict],
) -> dict:
    top = keywords[:8]
    top_lines = [
        f"- **{k.get('keyword')}** — ~{k.get('search_volume') or 0}/mo"
        + (f", CPC ${k.get('cpc')}" if k.get("cpc") is not None else "")
        for k in top
    ]

    intent_lines = []
    for intent in (
        "near_me",
        "online",
        "process",
        "prototype",
        "production",
        "material",
        "business",
        "price",
        "general_service",
        "local_branded",
    ):
        rows = by_intent.get(intent) or []
        if not rows:
            continue
        examples = ", ".join(
            f"{r['keyword']} ({r.get('search_volume') or 0})" for r in rows[:4]
        )
        intent_lines.append(f"- **{intent}**: {examples}")

    all_questions = []
    for block in paa:
        for q in block.get("questions") or []:
            all_questions.append(
                {
                    "question": q.get("question"),
                    "parent_keyword": block.get("parent_keyword"),
                }
            )
    q_lines = [
        f"- {q['question']}  _(from “{q['parent_keyword']}”)_"
        for q in all_questions[:12]
    ]

    # Competitor strength
    with_reviews = [c for c in competitors if (c.get("review_count") or 0) > 0]
    strong = sorted(
        with_reviews,
        key=lambda c: (c.get("review_count") or 0, c.get("rating") or 0),
        reverse=True,
    )[:5]
    comp_lines = [
        f"- **{c.get('name')}** — "
        f"{c.get('rating') or '?'}★ / {c.get('review_count') or 0} reviews"
        + (f" — {c.get('address')}" if c.get("address") else "")
        for c in strong
    ]
    if not comp_lines and competitors:
        comp_lines = [f"- **{c.get('name')}**" for c in competitors[:5]]

    actions = [
        "Bid/page content around “3d printing service” / “3d print service” "
        "(highest commercial volume).",
        "Answer People-Also-Ask questions on a Phoenix landing page (FAQ).",
        "Differentiate vs local shops with strong review counts "
        "(speed, materials, prototype→small batch).",
        "Consider process-specific pages (FDM / SLA / SLS) — people search tech names.",
    ]
    if any(i == "online" for i in by_intent):
        actions.append(
            "Expect competition from national online print bureaus; "
            "emphasize local pickup/speed for Phoenix."
        )

    md = "\n".join(
        [
            f"# Local 3D printing service market — {settings['city']}",
            "",
            f"_Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_",
            "",
            "## What people search for (top keywords)",
            *top_lines,
            "",
            "## Intent clusters",
            *(intent_lines or ["- (none)"]),
            "",
            "## Real customer questions (People Also Ask)",
            *(q_lines or ["- (none captured this run)"]),
            "",
            f"## Who already serves them (Maps, n={len(competitors)})",
            *(comp_lines or ["- (none captured this run)"]),
            "",
            "## Suggested actions",
            *[f"- {a}" for a in actions],
            "",
        ]
    )

    return {
        "headline": (
            f"In {settings['city']}, people mainly search generic service terms "
            f"({', '.join((k.get('keyword') or '') for k in top[:3])}), "
            f"with {len(competitors)} Maps businesses and "
            f"{len(all_questions)} captured FAQ-style questions."
        ),
        "top_keywords_md": top_lines,
        "intents_md": intent_lines,
        "questions_md": q_lines,
        "competitors_md": comp_lines,
        "actions": actions,
        "markdown": md,
    }


def market_cache_path(settings: dict) -> Path:
    d = Path(
        (load_yaml(DEFAULT_CONFIG).get("local_service") or {}).get(
            "market_cache_dir", DEFAULT_MARKET_CACHE_DIR
        )
    )
    return d / f"{settings['city_slug']}.json"


def write_market_report(settings: dict, report: dict) -> tuple[Path, Path]:
    slug = settings["city_slug"]
    out_json = Path(f"out/local_service_market_{slug}.json")
    out_md = Path(f"out/local_service_market_{slug}.md")
    out_json.parent.mkdir(parents=True, exist_ok=True)
    with out_json.open("w") as f:
        json.dump(report, f, indent=2)
    with out_md.open("w") as f:
        f.write(report.get("summary", {}).get("markdown") or "")
    return out_json, out_md


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def estimate(
    settings: dict,
    *,
    force: bool,
    paa_limit: int,
    skip_serp: bool,
    skip_maps: bool,
) -> None:
    cache = load_cache(cache_path(settings))
    kw_fresh = bool(cache and cache_is_fresh(cache, settings["cache_ttl_days"]) and not force)
    n_kw_tasks = 0 if kw_fresh else 2
    n_paa = 0 if skip_serp else paa_limit
    n_maps = 0 if skip_maps else 1
    cost = (
        n_kw_tasks * COST_KEYWORD_TASK
        + n_paa * COST_SERP_ORGANIC
        + n_maps * COST_SERP_MAPS
    )
    print("=== Local service MARKET scan — cost estimate ===")
    print(f"city:              {settings['city']}")
    print(f"location:          {settings.get('location_name')}")
    print(f"keyword cache:     {'fresh ($0)' if kw_fresh else f'cold (~{n_kw_tasks} tasks)'}")
    print(f"PAA SERPs:         {n_paa} × ~${COST_SERP_ORGANIC:.3f}")
    print(f"Maps SERP:         {n_maps} × ~${COST_SERP_MAPS:.3f}")
    print(f"ceiling total:     ~${cost:.2f}")
    print("(Actual SERP prices vary; keyword tasks ~$0.05–0.06 each.)")


def scan_market(
    config_path: str,
    *,
    city: str | None = None,
    force: bool = False,
    paa_limit: int = DEFAULT_PAA_LIMIT,
    skip_serp: bool = False,
    skip_maps: bool = False,
    maps_depth: int = DEFAULT_MAPS_DEPTH,
) -> None:
    cfg = load_yaml(config_path)
    settings = resolve_settings(cfg, city)
    ls = cfg.get("local_service") or {}
    paa_limit = int(ls.get("paa_limit") or paa_limit)
    maps_depth = int(ls.get("maps_depth") or maps_depth)

    print(f"City:     {settings['city']}")
    print(f"Location: {settings.get('location_name')}")

    # Market-level cache
    mpath = market_cache_path(settings)
    if mpath.exists() and not force:
        try:
            with mpath.open() as f:
                cached = json.load(f)
            if cache_is_fresh(cached, settings["cache_ttl_days"]):
                print(f"  market cache hit → {mpath}")
                out_json, out_md = write_market_report(settings, cached)
                print(cached.get("summary", {}).get("markdown", "")[:2500])
                print(f"\nWrote {out_json} and {out_md}")
                return
        except (json.JSONDecodeError, OSError, TypeError):
            pass

    # 1) Keywords
    print("\n== 1/4 Keywords + related ==")
    kw_report = ensure_keywords(settings, force=force, config_path=config_path)
    keywords = enrich_keywords_with_intent(list(kw_report.get("keywords") or []))
    all_kw = enrich_keywords_with_intent(
        list(kw_report.get("all_keywords") or keywords)
    )
    # Use broader related set for intent groups if available
    by_intent = group_by_intent(all_kw if len(all_kw) > len(keywords) else keywords)

    paa: list[dict] = []
    competitors: list[dict] = []
    maps_query = ""
    serp_cost = 0.0
    maps_cost = 0.0

    need_api = not skip_serp or not skip_maps
    login = password = ""
    if need_api:
        try:
            login, password = get_credentials()
        except SystemExit:
            print("  [warn] no DataForSEO creds — skipping SERP/Maps")
            skip_serp = skip_maps = True

    # 2) PAA
    print("\n== 2/4 People Also Ask ==")
    if skip_serp:
        print("  skipped")
    else:
        paa, serp_cost = collect_people_also_ask(
            keywords, settings, login, password, paa_limit=paa_limit
        )

    # 3) Maps competitors
    print("\n== 3/4 Local competitors (Maps) ==")
    if skip_maps:
        print("  skipped")
    else:
        competitors, maps_cost, maps_query = collect_competitors(
            settings, login, password, depth=maps_depth
        )

    # Merge local_pack previews into competitors if maps empty
    if not competitors:
        seen = set()
        for block in paa:
            for lp in block.get("local_pack_preview") or []:
                name = lp.get("name")
                if name and name not in seen:
                    seen.add(name)
                    competitors.append(lp)

    # 4) Summary
    print("\n== 4/4 Report ==")
    summary = build_summary(settings, keywords, by_intent, paa, competitors)
    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    report = {
        "city": settings["city"],
        "city_slug": settings["city_slug"],
        "location_name": settings.get("location_name"),
        "location_code": settings.get("location_code"),
        "fetched_at": fetched_at,
        "costs_reported": {
            "serp_paa_usd": serp_cost,
            "maps_usd": maps_cost,
            "total_serp_usd": serp_cost + maps_cost,
        },
        "top_keywords": keywords,
        "related_by_intent": by_intent,
        "people_also_ask": paa,
        "local_competitors": competitors,
        "maps_query": maps_query,
        "summary": summary,
        "notes": (
            "Keyword volumes are location-targeted Google Ads data. "
            "PAA and Maps come from live SERP/Maps and may vary by day."
        ),
    }

    mpath.parent.mkdir(parents=True, exist_ok=True)
    with mpath.open("w") as f:
        json.dump(report, f, indent=2)

    out_json, out_md = write_market_report(settings, report)
    print(summary["markdown"])
    print(f"Wrote {out_json}")
    print(f"Wrote {out_md}")
    print(f"Market cache → {mpath}")
    if serp_cost or maps_cost:
        print(
            f"SERP costs this run: PAA ${serp_cost:.4f} + Maps ${maps_cost:.4f} "
            f"= ${serp_cost + maps_cost:.4f}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Local 3D printing service market research (keywords + PAA + competitors)."
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--city", default=None, help='e.g. "Phoenix, AZ"')
    parser.add_argument("--estimate", action="store_true")
    parser.add_argument("--force", action="store_true", help="Ignore caches")
    parser.add_argument(
        "--paa-limit",
        type=int,
        default=DEFAULT_PAA_LIMIT,
        help=f"How many keywords to pull People Also Ask for (default {DEFAULT_PAA_LIMIT})",
    )
    parser.add_argument("--skip-serp", action="store_true", help="Skip PAA SERP calls")
    parser.add_argument("--skip-maps", action="store_true", help="Skip Maps competitor call")
    parser.add_argument(
        "--maps-depth",
        type=int,
        default=DEFAULT_MAPS_DEPTH,
        help=f"Max Maps businesses to keep (default {DEFAULT_MAPS_DEPTH})",
    )
    args = parser.parse_args()

    cfg = load_yaml(args.config)
    settings = resolve_settings(cfg, args.city)

    if args.estimate:
        estimate(
            settings,
            force=args.force,
            paa_limit=args.paa_limit,
            skip_serp=args.skip_serp,
            skip_maps=args.skip_maps,
        )
        sys.exit(0)

    scan_market(
        args.config,
        city=args.city,
        force=args.force,
        paa_limit=args.paa_limit,
        skip_serp=args.skip_serp,
        skip_maps=args.skip_maps,
        maps_depth=args.maps_depth,
    )
