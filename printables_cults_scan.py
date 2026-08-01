#!/usr/bin/env python3
"""
printables_cults_scan.py
------------------------
Demand-side marketplace engagement for each product:
  downloads, makes (prints shared), likes/favorites on Printables + Cults3D.

Approach (simple, resilient):
  1. Search each site by product keyword (prefer marketplace_keywords).
  2. Take the top N model hits from the first results page.
  3. Fetch per-model engagement stats.
  4. Aggregate: sum + top-model metrics per product.

Printables: search HTML for /model/<id>, then GraphQL
  print(id) → downloadCount, likesCount, makesCount
  (public api.printables.com/graphql — no auth)

Cults3D: search HTML for /3d-model/ links, open model pages, parse
  "N downloads / likes / makes" style text (structure can change).

USAGE:
  python3 printables_cults_scan.py
  python3 printables_cults_scan.py --smoke
  python3 printables_cults_scan.py --top 5 --delay 2
  python3 printables_cults_scan.py --skip-cults

OUTPUT:
  out/printables_cults_signal.csv  — one row per product
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
import urllib.parse
from dataclasses import dataclass, field

import requests
import yaml
from bs4 import BeautifulSoup

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
DEFAULT_DELAY_S = 1.5
DEFAULT_TIMEOUT_S = 25
DEFAULT_TOP_N = 5
DEFAULT_RETRIES = 3


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


def product_search_queries(product: dict, max_queries: int = 4) -> list[str]:
    """
    Ladder of search queries: specific marketplace terms first, then broader
    search_volume / discovery keywords. Ultra-specific brand+part phrases often
    return zero Printables hits, so keep broader fallbacks in the list.
    """
    buckets = [
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


def product_row(
    product: dict,
    printables: SiteAggregate,
    cults: SiteAggregate,
) -> dict:
    name = product["name"]
    p_dl = printables.downloads_sum
    c_dl = cults.downloads_sum
    p_mk = printables.makes_sum
    c_mk = cults.makes_sum
    p_lk = printables.likes_sum
    c_lk = cults.likes_sum

    def add_opt(a, b):
        if a is None and b is None:
            return None
        return (a or 0) + (b or 0)

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
        "community_downloads": fmt_metric(add_opt(p_dl, c_dl)),
        "community_makes": fmt_metric(add_opt(p_mk, c_mk)),
        "community_likes": fmt_metric(add_opt(p_lk, c_lk)),
        "notes": "; ".join(
            x
            for x in [
                f"printables:{printables.error}" if printables.error else "",
                f"cults:{cults.error}" if cults.error else "",
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
        "community_downloads",
        "community_makes",
        "community_likes",
        "notes",
    ]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def scan(
    config_path: str,
    out_path: str,
    *,
    top_n: int = DEFAULT_TOP_N,
    delay_s: float = DEFAULT_DELAY_S,
    smoke: bool = False,
    skip_printables: bool = False,
    skip_cults: bool = False,
    max_queries: int = 2,
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
    rows: list[dict] = []

    for product in products:
        name = product["name"]
        queries = product_search_queries(product, max_queries=max_queries)
        print(f"\n== {name}")
        print(f"  queries: {queries}")

        if skip_printables:
            p_agg = SiteAggregate(error="skipped")
            p_agg.downloads_sum = None
            p_agg.makes_sum = None
            p_agg.likes_sum = None
        else:
            p_agg = scan_printables(queries, session, top_n, delay_s)
            print(
                f"  printables: models={p_agg.models_sampled} "
                f"dl_sum={p_agg.downloads_sum} makes={p_agg.makes_sum} "
                f"likes={p_agg.likes_sum} top={p_agg.top_downloads} "
                f"{(p_agg.top_name or '')[:50]!r}"
                + (f" ERR={p_agg.error}" if p_agg.error else "")
            )

        if skip_cults:
            c_agg = SiteAggregate(error="skipped")
            c_agg.downloads_sum = None
            c_agg.makes_sum = None
            c_agg.likes_sum = None
        else:
            c_agg = scan_cults(queries, session, top_n, delay_s)
            print(
                f"  cults:      models={c_agg.models_sampled} "
                f"dl_sum={c_agg.downloads_sum} makes={c_agg.makes_sum} "
                f"likes={c_agg.likes_sum} top={c_agg.top_downloads} "
                f"{(c_agg.top_name or '')[:50]!r}"
                + (f" ERR={c_agg.error}" if c_agg.error else "")
            )

        rows.append(product_row(product, p_agg, c_agg))
        time.sleep(delay_s)

    write_rows(rows, out_path)
    print(f"\nWrote {len(rows)} rows → {out_path}")
    # Quick ranking by community downloads
    def sort_key(r):
        v = r.get("community_downloads")
        return -1 if v == "ERR" else -(int(v) if v is not None else 0)

    ranked = sorted(rows, key=sort_key)
    print("\n=== Community downloads (Printables + Cults top hits) ===\n")
    for r in ranked:
        print(
            f"  {str(r['community_downloads']):>6}  {r['product'][:48]:<48}  "
            f"(P {r['printables_downloads']} / C {r['cults_downloads']})"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Scan Printables + Cults for downloads/makes/likes demand signal."
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
    parser.add_argument("--smoke", action="store_true", help="First product only")
    parser.add_argument("--skip-printables", action="store_true")
    parser.add_argument("--skip-cults", action="store_true")
    args = parser.parse_args()
    scan(
        args.config,
        args.out,
        top_n=args.top,
        delay_s=args.delay,
        smoke=args.smoke,
        skip_printables=args.skip_printables,
        skip_cults=args.skip_cults,
        max_queries=args.max_queries,
    )
