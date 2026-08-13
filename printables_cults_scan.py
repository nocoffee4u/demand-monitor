#!/usr/bin/env python3
"""
printables_cults_scan.py
------------------------
Community engagement signal for each product across maker platforms:

  Printables + Cults3D + MakerWorld + Thangs

Aggregates downloads / makes / likes into community_* totals so
score_demand.py keeps using the same columns.

Approach (simple, resilient, soft-fail per source):
  1. Search each site by product keyword (prefer marketplace_keywords).
  2. Take the top N model hits.
  3. Collect engagement stats (API or HTML).
  4. Sum into platform columns + community_* aggregates.

Sources
  Printables: search HTML → GraphQL print(id) (public, no auth)
  Cults3D:    search HTML → model page parse
  MakerWorld: public JSON  GET /api/v1/search-service/search/design
              (downloadCount, printCount, likeCount — no auth)
  Thangs:     best-effort HTML/API; often Cloudflare-blocked — soft-fails
              with zeros + notes without killing the whole community row

USAGE:
  python3 printables_cults_scan.py
  python3 printables_cults_scan.py --smoke
  python3 printables_cults_scan.py --estimate
  python3 printables_cults_scan.py --top 5 --delay 2
  python3 printables_cults_scan.py --skip-cults --skip-thangs

OUTPUT:
  out/printables_cults_signal.csv  — one row per product
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

import requests
import yaml
from bs4 import BeautifulSoup

from cache_utils import cache_get, cache_put, clamp_limit, load_cache, save_cache

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

GQL_HEADERS = {
    **BROWSER_HEADERS,
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Origin": "https://www.printables.com",
    "Referer": "https://www.printables.com/",
}

PRINTABLES_GQL = "https://api.printables.com/graphql/"
MAKERWORLD_SEARCH = "https://makerworld.com/api/v1/search-service/search/design"
DEFAULT_DELAY_S = 1.5
DEFAULT_TIMEOUT_S = 25
DEFAULT_TOP_N = 5
DEFAULT_RETRIES = 3
CACHE_PATH = Path("cache/community_platforms_cache.json")
DEFAULT_CACHE_TTL_DAYS = 28


@dataclass
class ModelEngagement:
    site: str
    model_id: str
    name: str
    url: str
    downloads: int | None = None
    makes: int | None = None
    likes: int | None = None
    detail: str = ""


@dataclass
class SiteAggregate:
    models_sampled: int = 0
    downloads_sum: int | None = 0
    makes_sum: int | None = 0
    likes_sum: int | None = 0
    top_downloads: int | None = 0
    top_makes: int | None = 0
    top_likes: int | None = 0
    top_name: str = ""
    top_url: str = ""
    error: str = ""
    models: list[ModelEngagement] = field(default_factory=list)


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def parse_human_number(raw: str) -> int | None:
    if raw is None:
        return None
    s = str(raw).strip().lower().replace(",", "").replace(" ", "")
    if not s:
        return None
    mult = 1.0
    if s.endswith("k"):
        mult = 1_000.0
        s = s[:-1]
    elif s.endswith("m"):
        mult = 1_000_000.0
        s = s[:-1]
    try:
        return int(round(float(s) * mult))
    except ValueError:
        return None


def http_get(
    url: str,
    *,
    headers: dict | None = None,
    timeout: float = DEFAULT_TIMEOUT_S,
    retries: int = DEFAULT_RETRIES,
    session: requests.Session | None = None,
) -> requests.Response:
    hdrs = headers or BROWSER_HEADERS
    getter = session.get if session is not None else requests.get
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            resp = getter(url, headers=hdrs, timeout=timeout)
            if resp.status_code in (429, 502, 503, 504):
                sleep_s = min(60.0, (2**attempt) * 3.0)
                print(
                    f"    [warn] HTTP {resp.status_code} {url[:70]}… "
                    f"sleep {sleep_s:.0f}s"
                )
                time.sleep(sleep_s)
                last_err = RuntimeError(f"HTTP {resp.status_code}")
                continue
            return resp
        except requests.RequestException as e:
            last_err = e
            time.sleep(min(30.0, (2**attempt) * 2.0))
    raise RuntimeError(f"GET failed after {retries} tries: {last_err}")


def _clean_query(kw: str) -> str:
    q = re.sub(r"\s+", " ", (kw or "").strip())
    q = re.sub(r"\b3d\s*printed\b", " ", q, flags=re.I)
    q = re.sub(r"\b3d\s*print\b", " ", q, flags=re.I)
    q = re.sub(r"\bprinted\b", " ", q, flags=re.I)
    return re.sub(r"\s+", " ", q).strip(" -_")


def product_search_queries(
    product: dict,
    max_queries: int = 4,
    *,
    platform: str | None = None,
) -> list[str]:
    """
    Ladder of search queries: platform override → marketplace terms → broader
    search_volume / discovery keywords. Ultra-specific brand+part phrases often
    return zero hits, so keep broader fallbacks in the list.
    """
    platform_key = {
        "makerworld": "makerworld_keywords",
        "thangs": "thangs_keywords",
        "printables": "printables_keywords",
        "cults": "cults_keywords",
    }.get(platform or "", "")
    buckets = [
        product.get(platform_key) or [] if platform_key else [],
        product.get("marketplace_keywords") or [],
        product.get("search_volume_keywords") or [],
        product.get("keywords") or [],
        [product.get("name") or ""],
    ]
    out: list[str] = []
    seen: set[str] = set()
    for bucket in buckets:
        for kw in bucket:
            q = _clean_query(kw)
            key = q.lower()
            if q and key not in seen:
                seen.add(key)
                out.append(q)
            if len(out) >= max_queries:
                return out
    return out or ["3d print"]


# Tokens too generic to count alone toward relevance.
_GENERIC_TOKENS = {
    "the",
    "a",
    "an",
    "for",
    "of",
    "and",
    "or",
    "to",
    "in",
    "on",
    "with",
    "by",
    "bike",
    "ebike",
    "mount",
    "holder",
    "cover",
    "guard",
    "clip",
    "clips",
    "bracket",
    "replacement",
    "print",
    "printed",
    "model",
    "part",
    "parts",
    "kit",
    "universal",
    "simple",
    "frame",
    "car",
    "phone",
    "camera",
    "drone",
    "accessory",
    "accessories",
}


def title_relevance(title: str, query: str) -> float:
    """
    Relevance of a model title/slug to a search query (0-1).
    Generic words (mount, bike, guard…) don't count alone; distinctive
    tokens (chainstay, radpower, vtx, rzr…) must match for a high score.
    """
    q_all = [
        t
        for t in re.split(r"\W+", (query or "").lower())
        if t and len(t) > 2 and t not in {"the", "a", "an", "for", "of", "and", "or", "to", "in", "on", "with", "by"}
    ]
    if not q_all:
        return 0.0
    distinctive = [t for t in q_all if t not in _GENERIC_TOKENS]
    title_l = (title or "").lower().replace("-", " ")
    if distinctive:
        hits = sum(1 for t in distinctive if t in title_l)
        return hits / len(distinctive)
    # Query is all generic words — fall back to full-token overlap.
    hits = sum(1 for t in q_all if t in title_l)
    return hits / len(q_all)


# ---------------------------------------------------------------------------
# Printables
# ---------------------------------------------------------------------------

def printables_search_ids(
    query: str,
    session: requests.Session,
    limit: int,
) -> list[str]:
    url = (
        "https://www.printables.com/search/models?q="
        + urllib.parse.quote(query)
    )
    resp = http_get(url, session=session)
    if resp.status_code == 403:
        # Confirmed via manual inspection (2026-08): the search HTML page is
        # behind a Cloudflare managed challenge ("Just a moment...",
        # cf-mitigated: challenge) — same class of block as Thangs. Not a
        # header/UA/rate issue: requests/curl cannot solve a JS challenge, so
        # retrying or tweaking headers here won't help. The GraphQL API
        # (api.printables.com/graphql/, used by printables_model_stats) is
        # NOT behind this challenge and continues to work normally — only
        # the HTML search page is blocked.
        raise RuntimeError(
            "printables search HTTP 403 (Cloudflare managed challenge — "
            "soft-fail this source; not fixable via headers/retry)"
        )
    if resp.status_code != 200:
        raise RuntimeError(f"printables search HTTP {resp.status_code}")
    # /model/12345-slug or "id":"12345"
    ids = list(dict.fromkeys(re.findall(r"/model/(\d+)", resp.text)))
    if not ids:
        ids = list(dict.fromkeys(re.findall(r'"id"\s*:\s*"?(\d{4,})"?', resp.text)))
    return ids[:limit]


def printables_model_stats(
    model_id: str,
    session: requests.Session,
) -> ModelEngagement:
    query = """
    query ($id: ID!) {
      print(id: $id) {
        id
        name
        slug
        downloadCount
        likesCount
        makesCount
      }
    }
    """
    try:
        resp = session.post(
            PRINTABLES_GQL,
            headers=GQL_HEADERS,
            json={"query": query, "variables": {"id": str(model_id)}},
            timeout=DEFAULT_TIMEOUT_S,
        )
    except requests.RequestException as e:
        return ModelEngagement(
            site="printables",
            model_id=str(model_id),
            name="",
            url=f"https://www.printables.com/model/{model_id}",
            detail=f"gql network error: {e}",
        )
    if resp.status_code != 200:
        return ModelEngagement(
            site="printables",
            model_id=str(model_id),
            name="",
            url=f"https://www.printables.com/model/{model_id}",
            detail=f"gql HTTP {resp.status_code}",
        )
    try:
        payload = resp.json()
    except ValueError:
        return ModelEngagement(
            site="printables",
            model_id=str(model_id),
            name="",
            url=f"https://www.printables.com/model/{model_id}",
            detail="gql non-json",
        )
    node = ((payload.get("data") or {}).get("print")) or {}
    if not node:
        err = payload.get("errors")
        return ModelEngagement(
            site="printables",
            model_id=str(model_id),
            name="",
            url=f"https://www.printables.com/model/{model_id}",
            detail=f"gql empty: {err}",
        )
    slug = node.get("slug") or ""
    url = (
        f"https://www.printables.com/model/{model_id}-{slug}"
        if slug
        else f"https://www.printables.com/model/{model_id}"
    )
    return ModelEngagement(
        site="printables",
        model_id=str(node.get("id") or model_id),
        name=str(node.get("name") or ""),
        url=url,
        downloads=_as_int(node.get("downloadCount")),
        makes=_as_int(node.get("makesCount")),
        likes=_as_int(node.get("likesCount")),
        detail="graphql",
    )


def _as_int(v) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def scan_printables(
    queries: list[str],
    session: requests.Session,
    top_n: int,
    delay_s: float,
    min_relevance: float = 0.5,
) -> SiteAggregate:
    agg = SiteAggregate()
    seen_ids: set[str] = set()
    models: list[ModelEngagement] = []
    try:
        for qi, query in enumerate(queries):
            if qi:
                time.sleep(delay_s)
            ids = printables_search_ids(query, session, limit=max(top_n * 2, 10))
            if not ids:
                print(f"    printables: 0 hits for {query!r}")
                continue
            for mid in ids:
                if mid in seen_ids:
                    continue
                seen_ids.add(mid)
                time.sleep(delay_s)
                m = printables_model_stats(mid, session)
                rel = max(
                    (title_relevance(m.name, q) for q in queries),
                    default=0.0,
                )
                if m.name and rel < min_relevance:
                    continue
                models.append(m)
                if len(models) >= top_n:
                    break
            if len(models) >= top_n:
                break
    except Exception as e:
        agg.error = str(e)
        if not models:
            agg.downloads_sum = None
            agg.makes_sum = None
            agg.likes_sum = None
            return agg

    return aggregate_models(models, site="printables", error=agg.error)


# ---------------------------------------------------------------------------
# Cults3D
# ---------------------------------------------------------------------------

def cults_search_urls(
    query: str,
    session: requests.Session,
    limit: int,
) -> list[str]:
    url = "https://cults3d.com/en/search?q=" + urllib.parse.quote(query)
    resp = http_get(url, session=session)
    if resp.status_code != 200:
        raise RuntimeError(f"cults search HTTP {resp.status_code}")
    soup = BeautifulSoup(resp.text, "html.parser")
    links: list[str] = []
    for a in soup.select("a[href*='/3d-model/']"):
        href = (a.get("href") or "").split("?")[0]
        if not href or "/3d-model/" not in href:
            continue
        if href.startswith("/"):
            href = "https://cults3d.com" + href
        if href not in links:
            links.append(href)
        if len(links) >= limit:
            break
    return links


def cults_model_stats(url: str, session: requests.Session) -> ModelEngagement:
    mid = url.rstrip("/").split("/")[-1]
    try:
        resp = http_get(url, session=session)
    except Exception as e:
        return ModelEngagement(
            site="cults", model_id=mid, name="", url=url, detail=str(e)
        )
    if resp.status_code != 200:
        return ModelEngagement(
            site="cults",
            model_id=mid,
            name="",
            url=url,
            detail=f"HTTP {resp.status_code}",
        )
    soup = BeautifulSoup(resp.text, "html.parser")
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.split("|")[0].strip()
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(" ", strip=True) or title

    text = soup.get_text("\n", strip=True)
    stats = {"downloads": None, "likes": None, "makes": None}
    # Lines like "348 downloads", "42 likes", "3 makes"
    for key in list(stats.keys()):
        m = re.search(rf"(?im)^(\d[\d,.\s]*[kKmM]?)\s+{key}s?\s*$", text)
        if not m:
            m = re.search(rf"(?im)^{key}s?\s+(\d[\d,.\s]*[kKmM]?)\s*$", text)
        if not m:
            m = re.search(rf"(?i)\b(\d[\d,.\s]*[kKmM]?)\s+{key}s?\b", text)
        if m:
            stats[key] = parse_human_number(m.group(1))

    # Fallback: HTML attributes / nearby labels
    if stats["downloads"] is None:
        m = re.search(
            r"(?is)downloads?[^0-9]{0,40}(\d[\d,.\s]*[kKmM]?)", resp.text
        )
        if m:
            stats["downloads"] = parse_human_number(m.group(1))

    return ModelEngagement(
        site="cults",
        model_id=mid,
        name=title,
        url=url,
        downloads=stats["downloads"],
        makes=stats["makes"],
        likes=stats["likes"],
        detail="html_parse",
    )


def scan_cults(
    queries: list[str],
    session: requests.Session,
    top_n: int,
    delay_s: float,
    min_relevance: float = 0.5,
) -> SiteAggregate:
    models: list[ModelEngagement] = []
    seen: set[str] = set()
    error = ""
    try:
        for qi, query in enumerate(queries):
            if qi:
                time.sleep(delay_s)
            urls = cults_search_urls(query, session, limit=max(top_n * 2, 10))
            if not urls:
                print(f"    cults: 0 hits for {query!r}")
                continue
            for url in urls:
                if url in seen:
                    continue
                seen.add(url)
                time.sleep(delay_s)
                m = cults_model_stats(url, session)
                slug = url.rstrip("/").split("/")[-1].replace("-", " ")
                rel = max(
                    max(title_relevance(m.name, q), title_relevance(slug, q))
                    for q in queries
                )
                if rel < min_relevance:
                    continue
                models.append(m)
                if len(models) >= top_n:
                    break
            if len(models) >= top_n:
                break
    except Exception as e:
        error = str(e)
        if not models:
            agg = SiteAggregate(error=error)
            agg.downloads_sum = None
            agg.makes_sum = None
            agg.likes_sum = None
            return agg
    return aggregate_models(models, site="cults", error=error)


# ---------------------------------------------------------------------------
# MakerWorld (public JSON search — no auth)
# ---------------------------------------------------------------------------

def makerworld_search_hits(
    query: str,
    session: requests.Session,
    limit: int,
    *,
    cache: dict | None = None,
    cache_ttl: int = DEFAULT_CACHE_TTL_DAYS,
) -> list[dict]:
    """
    GET makerworld.com/api/v1/search-service/search/design
    Returns hit dicts with downloadCount, printCount, likeCount, title, id.
    """
    # Cache key must use the same clamped limit as the request param
    req_limit = clamp_limit(limit, lo=1, hi=50)
    ckey = f"mw|{query}|{req_limit}"
    if cache is not None:
        cached = cache_get(cache, ckey, cache_ttl)
        if cached is not None:
            return list(cached.get("hits") or [])

    params = {
        "keyword": query,
        "limit": req_limit,
        "offset": 0,
        "orderBy": "downloadCount",
    }
    headers = {
        **BROWSER_HEADERS,
        "Accept": "application/json",
        "Origin": "https://makerworld.com",
        "Referer": "https://makerworld.com/",
    }
    resp = session.get(
        MAKERWORLD_SEARCH,
        params=params,
        headers=headers,
        timeout=DEFAULT_TIMEOUT_S,
    )
    if resp.status_code == 403:
        raise RuntimeError("makerworld HTTP 403 (blocked/rate-limited)")
    if resp.status_code != 200:
        raise RuntimeError(f"makerworld search HTTP {resp.status_code}")
    try:
        payload = resp.json()
    except ValueError as e:
        raise RuntimeError(f"makerworld non-json: {e}") from e
    hits = list(payload.get("hits") or [])
    if cache is not None:
        cache_put(cache, ckey, {"hits": hits[:req_limit]})
    return hits[:req_limit]


def scan_makerworld(
    queries: list[str],
    session: requests.Session,
    top_n: int,
    delay_s: float,
    min_relevance: float = 0.5,
    *,
    cache: dict | None = None,
    cache_ttl: int = DEFAULT_CACHE_TTL_DAYS,
) -> SiteAggregate:
    models: list[ModelEngagement] = []
    seen: set[str] = set()
    error = ""
    try:
        for qi, query in enumerate(queries):
            if qi:
                time.sleep(delay_s)
            try:
                hits = makerworld_search_hits(
                    query,
                    session,
                    limit=max(top_n * 2, 10),
                    cache=cache,
                    cache_ttl=cache_ttl,
                )
            except Exception as e:
                print(f"    makerworld: search fail {query!r}: {e}")
                if not error:
                    error = str(e)
                continue
            if not hits:
                print(f"    makerworld: 0 hits for {query!r}")
                continue
            for hit in hits:
                mid = str(hit.get("id") or "")
                if not mid or mid in seen:
                    continue
                seen.add(mid)
                title = str(hit.get("title") or hit.get("slug") or "")
                rel = max(
                    (title_relevance(title, q) for q in queries),
                    default=0.0,
                )
                if title and rel < min_relevance:
                    continue
                slug = hit.get("slug") or ""
                url = (
                    f"https://makerworld.com/en/{slug}-{mid}"
                    if slug
                    else f"https://makerworld.com/en/models/{mid}"
                )
                # MakerWorld: printCount ≈ makes; likeCount; downloadCount
                models.append(
                    ModelEngagement(
                        site="makerworld",
                        model_id=mid,
                        name=title,
                        url=url,
                        downloads=_as_int(hit.get("downloadCount")),
                        makes=_as_int(hit.get("printCount")),
                        likes=_as_int(hit.get("likeCount")),
                        detail="search_api",
                    )
                )
                if len(models) >= top_n:
                    break
            if len(models) >= top_n:
                break
    except Exception as e:
        error = str(e)
        if not models:
            agg = SiteAggregate(error=error)
            agg.downloads_sum = None
            agg.makes_sum = None
            agg.likes_sum = None
            return agg
    return aggregate_models(models, site="makerworld", error=error)


# ---------------------------------------------------------------------------
# Thangs (best-effort; often Cloudflare-blocked — soft-fail)
# ---------------------------------------------------------------------------

def thangs_search_urls(
    query: str,
    session: requests.Session,
    limit: int,
    *,
    cache: dict | None = None,
    cache_ttl: int = DEFAULT_CACHE_TTL_DAYS,
) -> list[str]:
    """
    Best-effort Thangs search. Returns model page URLs if parseable.
    Raises RuntimeError on hard HTTP failures (caller soft-fails).
    """
    ckey = f"thangs|{query}|{limit}"
    if cache is not None:
        cached = cache_get(cache, ckey, cache_ttl)
        if cached is not None:
            return list(cached.get("urls") or [])

    # Public search URL variants — Cloudflare often returns 403
    candidates = [
        "https://thangs.com/search/"
        + urllib.parse.quote(query)
        + "?scope=all",
        "https://thangs.com/explore?search="
        + urllib.parse.quote(query),
    ]
    last_status = None
    text = ""
    for url in candidates:
        resp = session.get(
            url,
            headers={
                **BROWSER_HEADERS,
                "Referer": "https://thangs.com/",
            },
            timeout=DEFAULT_TIMEOUT_S,
        )
        last_status = resp.status_code
        if resp.status_code == 403:
            # Cloudflare challenge — not retryable without browser
            raise RuntimeError(
                "thangs HTTP 403 (Cloudflare blocked — soft-fail this source)"
            )
        if resp.status_code == 200 and len(resp.text) > 500:
            text = resp.text
            break
    if not text:
        raise RuntimeError(f"thangs search HTTP {last_status}")

    urls: list[str] = []
    # Common path patterns: /mythangs/..., /designer/.../3d-model/..., /m/...
    for pat in (
        r'href="(https://thangs\.com/[^"]+)"',
        r'href="(/[^"]*(?:3d-model|model|m)/[^"]+)"',
    ):
        for m in re.finditer(pat, text, re.I):
            href = m.group(1)
            if href.startswith("/"):
                href = "https://thangs.com" + href
            if "thangs.com" not in href:
                continue
            if any(
                x in href.lower()
                for x in ("login", "signup", "cart", "static", ".js", ".css")
            ):
                continue
            if href not in urls:
                urls.append(href.split("?")[0])
            if len(urls) >= limit:
                break
        if len(urls) >= limit:
            break

    if cache is not None:
        cache_put(cache, ckey, {"urls": urls[:limit]})
    return urls[:limit]


def thangs_model_stats(url: str, session: requests.Session) -> ModelEngagement:
    mid = url.rstrip("/").split("/")[-1][:80]
    try:
        resp = session.get(
            url,
            headers={**BROWSER_HEADERS, "Referer": "https://thangs.com/"},
            timeout=DEFAULT_TIMEOUT_S,
        )
    except Exception as e:
        return ModelEngagement(
            site="thangs", model_id=mid, name="", url=url, detail=str(e)
        )
    if resp.status_code == 403:
        return ModelEngagement(
            site="thangs",
            model_id=mid,
            name="",
            url=url,
            detail="HTTP 403 cloudflare",
        )
    if resp.status_code != 200:
        return ModelEngagement(
            site="thangs",
            model_id=mid,
            name="",
            url=url,
            detail=f"HTTP {resp.status_code}",
        )
    soup = BeautifulSoup(resp.text, "html.parser")
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.split("|")[0].strip()
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(" ", strip=True) or title

    downloads = likes = makes = None
    # JSON-LD or embedded metrics
    for pat, key in (
        (r'"downloadCount"\s*:\s*(\d+)', "downloads"),
        (r'"downloads"\s*:\s*(\d+)', "downloads"),
        (r'"likeCount"\s*:\s*(\d+)', "likes"),
        (r'"likes"\s*:\s*(\d+)', "likes"),
        (r'"printCount"\s*:\s*(\d+)', "makes"),
    ):
        m = re.search(pat, resp.text)
        if m:
            val = int(m.group(1))
            if key == "downloads" and downloads is None:
                downloads = val
            elif key == "likes" and likes is None:
                likes = val
            elif key == "makes" and makes is None:
                makes = val

    text = soup.get_text("\n", strip=True)
    if downloads is None:
        m = re.search(r"(?im)(\d[\d,.\s]*[kKmM]?)\s+downloads?\b", text)
        if m:
            downloads = parse_human_number(m.group(1))
    if likes is None:
        m = re.search(r"(?im)(\d[\d,.\s]*[kKmM]?)\s+likes?\b", text)
        if m:
            likes = parse_human_number(m.group(1))

    return ModelEngagement(
        site="thangs",
        model_id=mid,
        name=title,
        url=url,
        downloads=downloads,
        makes=makes,
        likes=likes,
        detail="html_parse",
    )


def scan_thangs(
    queries: list[str],
    session: requests.Session,
    top_n: int,
    delay_s: float,
    min_relevance: float = 0.5,
    *,
    cache: dict | None = None,
    cache_ttl: int = DEFAULT_CACHE_TTL_DAYS,
) -> SiteAggregate:
    models: list[ModelEngagement] = []
    seen: set[str] = set()
    error = ""
    try:
        for qi, query in enumerate(queries):
            if qi:
                time.sleep(delay_s)
            try:
                urls = thangs_search_urls(
                    query,
                    session,
                    limit=max(top_n * 2, 8),
                    cache=cache,
                    cache_ttl=cache_ttl,
                )
            except Exception as e:
                error = str(e)
                print(f"    thangs: search fail {query!r}: {e}")
                # Cloudflare / hard block — stop trying further queries
                if "403" in str(e) or "Cloudflare" in str(e):
                    break
                continue
            if not urls:
                print(f"    thangs: 0 hits for {query!r}")
                continue
            for url in urls:
                if url in seen:
                    continue
                seen.add(url)
                time.sleep(delay_s)
                m = thangs_model_stats(url, session)
                slug = url.rstrip("/").split("/")[-1].replace("-", " ")
                rel = max(
                    max(title_relevance(m.name, q), title_relevance(slug, q))
                    for q in queries
                )
                if m.name and rel < min_relevance:
                    continue
                models.append(m)
                if len(models) >= top_n:
                    break
            if len(models) >= top_n:
                break
    except Exception as e:
        error = str(e)
        if not models:
            agg = SiteAggregate(error=error)
            agg.downloads_sum = None
            agg.makes_sum = None
            agg.likes_sum = None
            return agg
    if error and not models:
        agg = SiteAggregate(error=error)
        # Soft empty (not invent engagement) — zeros for aggregate, not ERR null
        # when blocked so community totals from other platforms still work
        agg.downloads_sum = 0
        agg.makes_sum = 0
        agg.likes_sum = 0
        return agg
    return aggregate_models(models, site="thangs", error=error)


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def aggregate_models(
    models: list[ModelEngagement],
    *,
    site: str,
    error: str = "",
) -> SiteAggregate:
    usable = [
        m
        for m in models
        if m.downloads is not None or m.makes is not None or m.likes is not None
    ]
    agg = SiteAggregate(error=error, models=models)
    if not usable and not models:
        agg.downloads_sum = None
        agg.makes_sum = None
        agg.likes_sum = None
        agg.error = error or "no models found"
        return agg

    agg.models_sampled = len(models)
    # Treat missing metric as 0 for sums so one broken field doesn't null the row
    dls = [m.downloads or 0 for m in models]
    mks = [m.makes or 0 for m in models]
    lks = [m.likes or 0 for m in models]
    agg.downloads_sum = sum(dls)
    agg.makes_sum = sum(mks)
    agg.likes_sum = sum(lks)

    # Top model by downloads (then likes)
    ranked = sorted(
        models,
        key=lambda m: (m.downloads or 0, m.likes or 0, m.makes or 0),
        reverse=True,
    )
    if ranked:
        top = ranked[0]
        agg.top_downloads = top.downloads or 0
        agg.top_makes = top.makes or 0
        agg.top_likes = top.likes or 0
        agg.top_name = top.name
        agg.top_url = top.url
    return agg


def fmt_metric(v: int | None) -> str | int:
    return "ERR" if v is None else v


def _add_opt(*vals) -> int | None:
    """Sum optional metrics; None only if all inputs are None."""
    if all(v is None for v in vals):
        return None
    return sum(int(v or 0) for v in vals)


def product_row(
    product: dict,
    printables: SiteAggregate,
    cults: SiteAggregate,
    makerworld: SiteAggregate | None = None,
    thangs: SiteAggregate | None = None,
) -> dict:
    name = product["name"]
    mw = makerworld or SiteAggregate()
    th = thangs or SiteAggregate()
    if makerworld is None:
        mw.downloads_sum = mw.makes_sum = mw.likes_sum = None
    if thangs is None:
        th.downloads_sum = th.makes_sum = th.likes_sum = None

    p_dl, c_dl = printables.downloads_sum, cults.downloads_sum
    p_mk, c_mk = printables.makes_sum, cults.makes_sum
    p_lk, c_lk = printables.likes_sum, cults.likes_sum
    m_dl, m_mk, m_lk = mw.downloads_sum, mw.makes_sum, mw.likes_sum
    t_dl, t_mk, t_lk = th.downloads_sum, th.makes_sum, th.likes_sum

    return {
        "product": name,
        "category": product.get("category") or "",
        "printables_downloads": fmt_metric(p_dl),
        "printables_makes": fmt_metric(p_mk),
        "printables_likes": fmt_metric(p_lk),
        "printables_models_sampled": printables.models_sampled,
        "printables_top_downloads": fmt_metric(
            None
            if (printables.error and not printables.models_sampled)
            else printables.top_downloads
        ),
        "printables_top_name": printables.top_name,
        "cults_downloads": fmt_metric(c_dl),
        "cults_makes": fmt_metric(c_mk),
        "cults_likes": fmt_metric(c_lk),
        "cults_models_sampled": cults.models_sampled,
        "cults_top_downloads": fmt_metric(cults.top_downloads),
        "cults_top_name": cults.top_name,
        "makerworld_downloads": fmt_metric(m_dl),
        "makerworld_makes": fmt_metric(m_mk),
        "makerworld_likes": fmt_metric(m_lk),
        "makerworld_models_sampled": mw.models_sampled,
        "makerworld_top_downloads": fmt_metric(
            None if (mw.error and not mw.models_sampled) else mw.top_downloads
        ),
        "makerworld_top_name": mw.top_name,
        "thangs_downloads": fmt_metric(t_dl),
        "thangs_makes": fmt_metric(t_mk),
        "thangs_likes": fmt_metric(t_lk),
        "thangs_models_sampled": th.models_sampled,
        "thangs_top_downloads": fmt_metric(
            None if (th.error and not th.models_sampled) else th.top_downloads
        ),
        "thangs_top_name": th.top_name,
        # Sum across all platforms that returned numbers (soft-fail sites
        # contribute 0 when empty/blocked, not inventing engagement)
        "community_downloads": fmt_metric(
            _add_opt(p_dl, c_dl, m_dl, t_dl)
        ),
        "community_makes": fmt_metric(_add_opt(p_mk, c_mk, m_mk, t_mk)),
        "community_likes": fmt_metric(_add_opt(p_lk, c_lk, m_lk, t_lk)),
        "notes": "; ".join(
            x
            for x in [
                f"printables:{printables.error}" if printables.error else "",
                f"cults:{cults.error}" if cults.error else "",
                f"makerworld:{mw.error}" if mw.error else "",
                f"thangs:{th.error}" if th.error else "",
            ]
            if x
        ),
    }


def write_rows(rows: list[dict], path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fields = [
        "product",
        "category",
        "printables_downloads",
        "printables_makes",
        "printables_likes",
        "printables_models_sampled",
        "printables_top_downloads",
        "printables_top_name",
        "cults_downloads",
        "cults_makes",
        "cults_likes",
        "cults_models_sampled",
        "cults_top_downloads",
        "cults_top_name",
        "makerworld_downloads",
        "makerworld_makes",
        "makerworld_likes",
        "makerworld_models_sampled",
        "makerworld_top_downloads",
        "makerworld_top_name",
        "thangs_downloads",
        "thangs_makes",
        "thangs_likes",
        "thangs_models_sampled",
        "thangs_top_downloads",
        "thangs_top_name",
        "community_downloads",
        "community_makes",
        "community_likes",
        "notes",
    ]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def _empty_skipped() -> SiteAggregate:
    agg = SiteAggregate(error="skipped")
    agg.downloads_sum = None
    agg.makes_sum = None
    agg.likes_sum = None
    return agg


def estimate(config_path: str, max_queries: int = 2) -> None:
    cfg = load_config(config_path)
    products = list(cfg.get("products") or [])
    n = len(products)
    # Rough upper bound: 4 platforms × products × queries × (1 search + top_n details)
    print("Community platforms estimate (cold, all sources on):")
    print(f"  products:           {n}")
    print(f"  queries/product:    up to {max_queries}")
    print("  platforms:          Printables, Cults3D, MakerWorld, Thangs")
    print(
        "  rough HTTP calls:   ~"
        f"{n * max_queries * 4 * 3}  "
        "(search + model pages/API; cache cuts MakerWorld/Thangs repeats)"
    )
    print(f"  cache:              {CACHE_PATH} TTL {DEFAULT_CACHE_TTL_DAYS}d")
    print("  soft-fail:          one platform down does not kill the community row")


def scan(
    config_path: str,
    out_path: str,
    *,
    top_n: int = DEFAULT_TOP_N,
    delay_s: float = DEFAULT_DELAY_S,
    smoke: bool = False,
    skip_printables: bool = False,
    skip_cults: bool = False,
    skip_makerworld: bool = False,
    skip_thangs: bool = False,
    max_queries: int = 2,
    use_cache: bool = True,
) -> None:
    cfg = load_config(config_path)
    products = list(cfg.get("products") or [])
    if not products:
        print("ERROR: no products in config")
        sys.exit(1)
    if smoke:
        products = products[:1]
        print(f"SMOKE mode: only {products[0]['name']!r}")

    session = requests.Session()
    cache = load_cache(CACHE_PATH) if use_cache else {}
    rows: list[dict] = []
    # Per-platform run status: ok | skipped | error (for Dashboard coverage chip)
    platform_status: dict[str, dict[str, str]] = {
        "printables": {"status": "skipped", "error": ""},
        "cults": {"status": "skipped", "error": ""},
        "makerworld": {"status": "skipped", "error": ""},
        "thangs": {"status": "skipped", "error": ""},
    }

    def _track(platform: str, agg: SiteAggregate, skipped: bool) -> None:
        if skipped:
            platform_status[platform] = {"status": "skipped", "error": ""}
            return
        # Hard failure with no models → error (unless we already had a good product)
        if agg.error and not agg.models_sampled:
            if platform_status[platform].get("status") != "ok":
                platform_status[platform] = {
                    "status": "error",
                    "error": (agg.error or "")[:200],
                }
            return
        # Completed without blocking error (even if zero relevant models)
        platform_status[platform] = {"status": "ok", "error": ""}

    for product in products:
        name = product["name"]
        # Shared ladder for Printables/Cults; platform overrides for MW/Thangs
        queries = product_search_queries(product, max_queries=max_queries)
        mw_queries = product_search_queries(
            product, max_queries=max_queries, platform="makerworld"
        )
        th_queries = product_search_queries(
            product, max_queries=max_queries, platform="thangs"
        )
        print(f"\n== {name}")
        print(f"  queries: {queries}")

        if skip_printables:
            p_agg = _empty_skipped()
        else:
            p_agg = scan_printables(queries, session, top_n, delay_s)
            print(
                f"  printables: models={p_agg.models_sampled} "
                f"dl_sum={p_agg.downloads_sum} makes={p_agg.makes_sum} "
                f"likes={p_agg.likes_sum} top={p_agg.top_downloads} "
                f"{(p_agg.top_name or '')[:50]!r}"
                + (f" ERR={p_agg.error}" if p_agg.error else "")
            )
        _track("printables", p_agg, skip_printables)

        if skip_cults:
            c_agg = _empty_skipped()
        else:
            c_agg = scan_cults(queries, session, top_n, delay_s)
            print(
                f"  cults:      models={c_agg.models_sampled} "
                f"dl_sum={c_agg.downloads_sum} makes={c_agg.makes_sum} "
                f"likes={c_agg.likes_sum} top={c_agg.top_downloads} "
                f"{(c_agg.top_name or '')[:50]!r}"
                + (f" ERR={c_agg.error}" if c_agg.error else "")
            )
        _track("cults", c_agg, skip_cults)

        if skip_makerworld:
            m_agg = _empty_skipped()
        else:
            try:
                m_agg = scan_makerworld(
                    mw_queries,
                    session,
                    top_n,
                    delay_s,
                    cache=cache if use_cache else None,
                    cache_ttl=DEFAULT_CACHE_TTL_DAYS,
                )
            except Exception as e:
                m_agg = SiteAggregate(error=str(e))
                m_agg.downloads_sum = 0
                m_agg.makes_sum = 0
                m_agg.likes_sum = 0
            print(
                f"  makerworld: models={m_agg.models_sampled} "
                f"dl_sum={m_agg.downloads_sum} makes={m_agg.makes_sum} "
                f"likes={m_agg.likes_sum} top={m_agg.top_downloads} "
                f"{(m_agg.top_name or '')[:50]!r}"
                + (f" ERR={m_agg.error}" if m_agg.error else "")
            )
        _track("makerworld", m_agg, skip_makerworld)

        if skip_thangs:
            t_agg = _empty_skipped()
        else:
            try:
                t_agg = scan_thangs(
                    th_queries,
                    session,
                    top_n,
                    delay_s,
                    cache=cache if use_cache else None,
                    cache_ttl=DEFAULT_CACHE_TTL_DAYS,
                )
            except Exception as e:
                t_agg = SiteAggregate(error=str(e))
                t_agg.downloads_sum = 0
                t_agg.makes_sum = 0
                t_agg.likes_sum = 0
            print(
                f"  thangs:     models={t_agg.models_sampled} "
                f"dl_sum={t_agg.downloads_sum} makes={t_agg.makes_sum} "
                f"likes={t_agg.likes_sum} top={t_agg.top_downloads} "
                f"{(t_agg.top_name or '')[:50]!r}"
                + (f" ERR={t_agg.error}" if t_agg.error else "")
            )
        _track("thangs", t_agg, skip_thangs)

        rows.append(product_row(product, p_agg, c_agg, m_agg, t_agg))
        time.sleep(delay_s)

    if use_cache:
        save_cache(CACHE_PATH, cache)

    write_rows(rows, out_path)
    # Sidecar for run_meta / Dashboard coverage chip (ok | skipped | error)
    ok_n = sum(1 for v in platform_status.values() if v.get("status") == "ok")
    meta_path = os.path.join(os.path.dirname(out_path) or "out", "community_platforms_meta.json")
    os.makedirs(os.path.dirname(meta_path) or "out", exist_ok=True)
    with open(meta_path, "w") as f:
        json.dump(
            {
                "platforms": platform_status,
                "ok_count": ok_n,
                "total": len(platform_status),
            },
            f,
            indent=2,
        )
    print(f"\nWrote {len(rows)} rows → {out_path}")
    print(
        f"Platform coverage: {ok_n}/{len(platform_status)} ok → {meta_path}"
    )

    def sort_key(r):
        v = r.get("community_downloads")
        return -1 if v == "ERR" else -(int(v) if v is not None else 0)

    ranked = sorted(rows, key=sort_key)
    print(
        "\n=== Community downloads "
        "(Printables + Cults + MakerWorld + Thangs) ===\n"
    )
    for r in ranked:
        print(
            f"  {str(r['community_downloads']):>6}  {r['product'][:42]:<42}  "
            f"(P {r['printables_downloads']} / C {r['cults_downloads']} / "
            f"MW {r['makerworld_downloads']} / T {r['thangs_downloads']})"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Scan Printables + Cults + MakerWorld + Thangs for "
            "downloads/makes/likes community demand signal."
        )
    )
    parser.add_argument("--config", default="config/products.yaml")
    parser.add_argument("--out", default="out/printables_cults_signal.csv")
    parser.add_argument(
        "--top",
        type=int,
        default=DEFAULT_TOP_N,
        help=f"Max models to sample per site per product (default {DEFAULT_TOP_N})",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY_S,
        help=f"Seconds between requests (default {DEFAULT_DELAY_S})",
    )
    parser.add_argument(
        "--max-queries",
        type=int,
        default=4,
        help="Keyword variants to try per product (default 4)",
    )
    parser.add_argument(
        "--estimate",
        action="store_true",
        help="Print rough call budget; no network scans",
    )
    parser.add_argument("--smoke", action="store_true", help="First product only")
    parser.add_argument("--skip-printables", action="store_true")
    parser.add_argument("--skip-cults", action="store_true")
    parser.add_argument("--skip-makerworld", action="store_true")
    parser.add_argument("--skip-thangs", action="store_true")
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable cache/community_platforms_cache.json",
    )
    args = parser.parse_args()
    if args.estimate:
        estimate(args.config, max_queries=args.max_queries)
        sys.exit(0)
    scan(
        args.config,
        args.out,
        top_n=args.top,
        delay_s=args.delay,
        smoke=args.smoke,
        skip_printables=args.skip_printables,
        skip_cults=args.skip_cults,
        skip_makerworld=args.skip_makerworld,
        skip_thangs=args.skip_thangs,
        max_queries=args.max_queries,
        use_cache=not args.no_cache,
    )
