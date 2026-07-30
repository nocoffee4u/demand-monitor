#!/usr/bin/env python3
"""
marketplace_scan.py
--------------------
Counts how many existing listings show up on maker marketplaces for each
product's keywords. A HIGH count means the design already exists many times
over (more competition, but also validates demand). A LOW/ZERO count for a
keyword you know riders want is a whitespace signal.

Adapters (see config/products.yaml → marketplaces):
  printables  — HTML search; prefers the page "N models" total, falls back to
                unique /model/<id> links on the first page.
  cults       — HTML search; parses "N search results" from the page title.
  thangs      — HTML search; parses "N Model(s)" from the page text.
  makerworld  — best-effort JSON API (HTML is Cloudflare-gated). Often returns
                empty/unrelated results for server-side clients; recorded as
                ERR when unusable so it doesn't fake a zero-competition signal.
  html        — generic CSS-selector scrape (legacy / custom sites).

USAGE:
  python3 marketplace_scan.py
  python3 marketplace_scan.py --config config/products.yaml --out out/marketplace_signal.csv
  python3 marketplace_scan.py --smoke   # one product, all marketplaces (debug)

LIMITATIONS:
  - Marketplace sites redesign HTML periodically; totals may break until
    adapters/regexes are updated.
  - First-page unique-link counts are a LOWER BOUND when the site doesn't
    expose a total (we prefer totals when available).
  - Run weekly, not in a tight loop. Respect each site's robots.txt / ToS.
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
import urllib.parse
from dataclasses import dataclass

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

JSON_HEADERS = {
    **BROWSER_HEADERS,
    "Accept": "application/json, text/plain, */*",
}

DEFAULT_DELAY_S = 2.0
DEFAULT_TIMEOUT_S = 25
DEFAULT_RETRIES = 3


@dataclass
class CountResult:
    count: int | None  # None → write ERR
    detail: str = ""
    source: str = ""  # how the count was derived


def parse_human_number(raw: str) -> int | None:
    """
    Parse counts like '9', '2,340', '5.3k', '1.2M'.
    Returns None if unparseable.
    """
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
    """GET with retries on transient errors (429/5xx/timeouts)."""
    hdrs = headers or BROWSER_HEADERS
    getter = session.get if session is not None else requests.get
    last_err: Exception | None = None

    for attempt in range(retries):
        try:
            resp = getter(url, headers=hdrs, timeout=timeout)
            if resp.status_code in (429, 502, 503, 504):
                sleep_s = min(60.0, (2**attempt) * 3.0)
                print(
                    f"    [warn] HTTP {resp.status_code} for {url[:80]}… "
                    f"(attempt {attempt + 1}/{retries}); sleep {sleep_s:.0f}s"
                )
                time.sleep(sleep_s)
                last_err = RuntimeError(f"HTTP {resp.status_code}")
                continue
            return resp
        except requests.RequestException as e:
            last_err = e
            sleep_s = min(30.0, (2**attempt) * 2.0)
            print(
                f"    [warn] request error for {url[:80]}…: {e} "
                f"(attempt {attempt + 1}/{retries}); sleep {sleep_s:.0f}s"
            )
            time.sleep(sleep_s)

    raise RuntimeError(f"failed after {retries} retries: {last_err}")


def looks_like_cloudflare(resp: requests.Response) -> bool:
    if resp.status_code in (403, 503):
        body = (resp.text or "")[:2000].lower()
        if "just a moment" in body or "cf-browser-verification" in body or "cloudflare" in body:
            return True
    title_hit = "just a moment" in (resp.text or "")[:1500].lower()
    return title_hit and "enable javascript" in (resp.text or "").lower()


# ---------------------------------------------------------------------------
# Adapters
# ---------------------------------------------------------------------------

def count_printables(query: str, session: requests.Session) -> CountResult:
    url = (
        "https://www.printables.com/search/models?q="
        + urllib.parse.quote(query)
    )
    resp = http_get(url, session=session)
    if resp.status_code != 200:
        return CountResult(None, f"HTTP {resp.status_code}", "error")
    if looks_like_cloudflare(resp):
        return CountResult(None, "cloudflare challenge", "error")

    soup = BeautifulSoup(resp.text, "html.parser")
    text = soup.get_text("\n", strip=True)

    # Prefer the site's own total ("2,340 models").
    m = re.search(r"([\d][\d,.]*)\s*models\b", text, re.I)
    if m:
        total = parse_human_number(m.group(1))
        if total is not None:
            return CountResult(total, f"page total '{m.group(0).strip()}'", "total_text")

    # Fallback: unique model IDs on the first results page (lower bound).
    ids: set[str] = set()
    for a in soup.select("a[href*='/model/']"):
        mm = re.search(r"/model/(\d+)", a.get("href") or "")
        if mm:
            ids.add(mm.group(1))
    return CountResult(
        len(ids),
        f"{len(ids)} unique /model/ ids on first page (lower bound)",
        "unique_links",
    )


def count_cults(query: str, session: requests.Session) -> CountResult:
    url = "https://cults3d.com/en/search?q=" + urllib.parse.quote(query)
    resp = http_get(url, session=session)
    if resp.status_code != 200:
        return CountResult(None, f"HTTP {resp.status_code}", "error")
    if looks_like_cloudflare(resp):
        return CountResult(None, "cloudflare challenge", "error")

    soup = BeautifulSoup(resp.text, "html.parser")
    title = soup.title.string if soup.title else ""
    # Title: '5.3k search results for 3D models…' or '4 search results…'
    m = re.search(r"([\d.,]+\s*[kKmM]?)\s*search results", title or "", re.I)
    if not m:
        m = re.search(
            r"([\d.,]+\s*[kKmM]?)\s*search results",
            soup.get_text(" ", strip=True),
            re.I,
        )
    if m:
        total = parse_human_number(m.group(1))
        if total is not None:
            return CountResult(total, f"title/total '{m.group(0).strip()}'", "total_text")

    # Fallback: unique model card links on the page.
    hrefs = set()
    for a in soup.select("a[href*='/3d-model/']"):
        href = (a.get("href") or "").split("?")[0]
        if href:
            hrefs.add(href)
    return CountResult(
        len(hrefs),
        f"{len(hrefs)} unique model links on first page (lower bound)",
        "unique_links",
    )


def count_thangs(query: str, session: requests.Session) -> CountResult:
    # Thangs puts the query in the path. Much of the UI is client-rendered;
    # when a total is server-rendered we can read it, otherwise ERR.
    url = (
        "https://thangs.com/search/"
        + urllib.parse.quote(query)
        + "?scope=all"
    )
    resp = http_get(url, session=session)
    if resp.status_code != 200:
        return CountResult(None, f"HTTP {resp.status_code}", "error")
    if looks_like_cloudflare(resp):
        return CountResult(None, "cloudflare challenge", "error")

    soup = BeautifulSoup(resp.text, "html.parser")
    text = soup.get_text(" ", strip=True)
    # Require a plausible count: no leading zeros, up to 7 digits, word "Model(s)".
    # Avoid matching CSS/IDs like "0001 Model" fragments.
    candidates = re.findall(r"\b([1-9][\d,]{0,6})\s+Models?\b", text, re.I)
    parsed = [parse_human_number(c) for c in candidates]
    parsed = [p for p in parsed if p is not None]
    if parsed:
        # If multiple matches, the search total is typically the first/largest
        # reasonable figure under 1M (site chrome can contain other counts).
        plausible = [p for p in parsed if p < 1_000_000]
        if plausible:
            total = max(plausible) if len(set(plausible)) == 1 else plausible[0]
            # Prefer the first candidate when they differ (usually the result total).
            total = parse_human_number(candidates[0]) or plausible[0]
            return CountResult(total, f"page total from {candidates!r}", "total_text")

    return CountResult(None, "could not parse model total from page", "error")


def count_makerworld(query: str, session: requests.Session) -> CountResult:
    """
    MakerWorld HTML search is Cloudflare-gated. Their JSON search endpoint
    accepts unauthenticated requests but does NOT filter by keyword:
      - `keyword`  → always total=0 / empty hits
      - `keywords` → always a global hot list (~10000) unrelated to the query

    Returning either would poison competition scoring (fake zero OR fake
    saturation). We only accept a response when top-hit titles clearly share
    tokens with the query; otherwise ERR.
    """
    api = "https://makerworld.com/api/v1/search-service/select/design"
    headers = {
        **JSON_HEADERS,
        "Origin": "https://makerworld.com",
        "Referer": (
            "https://makerworld.com/en/search/models?keyword="
            + urllib.parse.quote(query)
        ),
    }
    attempts = [
        {"keyword": query, "limit": 20, "offset": 0},
        {"keywords": query, "limit": 20, "offset": 0, "orderBy": "score"},
    ]
    tokens = [t for t in re.split(r"\W+", query.lower()) if len(t) >= 3]
    if not tokens:
        return CountResult(None, "query too short to validate relevance", "error")

    saw_response = False
    for params in attempts:
        try:
            resp = session.get(
                api, params=params, headers=headers, timeout=DEFAULT_TIMEOUT_S
            )
        except requests.RequestException as e:
            return CountResult(None, f"network error: {e}", "error")

        if looks_like_cloudflare(resp):
            return CountResult(None, "cloudflare challenge", "error")
        if resp.status_code != 200:
            continue
        try:
            payload = resp.json()
        except ValueError:
            continue

        saw_response = True
        hits = payload.get("hits") or []
        total = payload.get("total")
        if not hits:
            # Do NOT treat empty as zero — unauthenticated `keyword` always
            # returns empty even for huge niches like "gopro mount".
            continue

        titles = [
            (h.get("titleTranslated") or h.get("title") or "").lower()
            for h in hits[:10]
        ]
        relevant = sum(1 for title in titles if any(tok in title for tok in tokens))
        if relevant == 0:
            continue

        if isinstance(total, (int, float)) and total >= 0:
            return CountResult(
                int(total),
                f"API total={int(total)} ({relevant}/{len(titles)} top hits relevant)",
                "api",
            )
        return CountResult(
            len(hits),
            f"API hits page={len(hits)} (no total; {relevant} relevant)",
            "api",
        )

    if saw_response:
        return CountResult(
            None,
            "API up but results untrusted (no keyword filter for server clients)",
            "error",
        )
    return CountResult(None, "API unreachable", "error")


def count_generic_html(
    query: str,
    mp: dict,
    session: requests.Session,
) -> CountResult:
    """Legacy config-driven CSS selector counter (unique hrefs)."""
    template = mp.get("search_url_template")
    selector = mp.get("result_selector")
    if not template or not selector:
        return CountResult(None, "missing search_url_template or result_selector", "error")

    url = template.format(query=urllib.parse.quote(query))
    resp = http_get(url, session=session)
    if resp.status_code != 200:
        return CountResult(None, f"HTTP {resp.status_code}", "error")
    if looks_like_cloudflare(resp):
        return CountResult(None, "cloudflare challenge", "error")

    soup = BeautifulSoup(resp.text, "html.parser")

    total_regex = mp.get("total_regex")
    if total_regex:
        text = soup.get_text("\n", strip=True)
        title = soup.title.string if soup.title else ""
        for corpus in (title, text):
            m = re.search(total_regex, corpus or "", re.I)
            if m:
                total = parse_human_number(m.group(1))
                if total is not None:
                    return CountResult(total, f"total_regex '{m.group(0).strip()}'", "total_text")

    id_regex = mp.get("id_regex")
    matches = soup.select(selector)
    if id_regex:
        ids: set[str] = set()
        for el in matches:
            href = el.get("href") if hasattr(el, "get") else None
            blob = href or el.get_text(" ", strip=True)
            m = re.search(id_regex, blob or "")
            if m:
                ids.add(m.group(1))
        return CountResult(
            len(ids),
            f"{len(ids)} unique ids via {selector}",
            "unique_links",
        )

    # Deduplicate identical hrefs even without id_regex.
    hrefs = set()
    plain = 0
    for el in matches:
        href = el.get("href") if hasattr(el, "get") else None
        if href:
            hrefs.add(href.split("?")[0])
        else:
            plain += 1
    count = len(hrefs) + plain
    return CountResult(count, f"{count} nodes via {selector}", "selector")


ADAPTERS = {
    "printables": count_printables,
    "cults": count_cults,
    "thangs": count_thangs,
    "makerworld": count_makerworld,
}


def resolve_adapter_name(mp: dict) -> str:
    return (mp.get("adapter") or mp.get("name") or "html").lower()


def count_for_marketplace(
    mp: dict,
    query: str,
    session: requests.Session,
) -> CountResult:
    name = resolve_adapter_name(mp)
    if name in ADAPTERS:
        return ADAPTERS[name](query, session)
    if name == "html" or mp.get("search_url_template"):
        return count_generic_html(query, mp, session)
    return CountResult(None, f"unknown adapter '{name}'", "error")


def marketplace_query_variants(keywords: list[str], max_variants: int = 4) -> list[str]:
    """
    Build search variants for competition checks.

    Product keywords often include '3d printed' / 'print' for Reddit discovery.
    Those tokens kill marketplace recall (Printables returns 0 for
    '3d printed gopro mount bike' but 2340 for 'gopro mount'). We try the
    original terms plus cleaned variants; the scan keeps the MAX count as
    the competition signal.

    Caps at max_variants so a full product list stays within a weekly run.
    """
    variants: list[str] = []
    seen: set[str] = set()

    def add(q: str) -> None:
        q = re.sub(r"\s+", " ", (q or "").strip())
        key = q.lower()
        if q and key not in seen:
            seen.add(key)
            variants.append(q)

    def strip_print_meta(kw: str) -> str:
        cleaned = re.sub(r"\b3d\s*printed\b", " ", kw, flags=re.I)
        cleaned = re.sub(r"\b3d\s*print\b", " ", cleaned, flags=re.I)
        cleaned = re.sub(r"\bprinted\b", " ", cleaned, flags=re.I)
        cleaned = re.sub(r"\bprint\b", " ", cleaned, flags=re.I)
        return re.sub(r"\s+", " ", cleaned).strip(" -_")

    def drop_trailing_platform(kw: str) -> str:
        short = re.sub(
            r"\s+\b(mtb|bike|ebike|e-bike|drone|fpv|utv|rzr|car)\b\s*$",
            "",
            kw,
            flags=re.I,
        ).strip()
        return short if short != kw and len(short.split()) >= 2 else ""

    # 1) Cleaned primary (+ careful short form) first — best recall.
    if keywords:
        primary_clean = strip_print_meta(keywords[0])
        add(primary_clean)
        short = drop_trailing_platform(primary_clean)
        if short:
            add(short)

    # 2) Cleaned remaining keywords.
    for kw in keywords[1:3]:
        add(strip_print_meta(kw))
        if len(variants) >= max_variants:
            return variants[:max_variants]

    # 3) Originals (brand phrases).
    for kw in keywords[:2]:
        add(kw)
        if len(variants) >= max_variants:
            break

    return variants[:max_variants]


def best_count_for_marketplace(
    mp: dict,
    keywords: list[str],
    session: requests.Session,
    delay_s: float,
) -> CountResult:
    """Try keyword variants; return the highest trusted count (max competition)."""
    variants = marketplace_query_variants(keywords)
    best: CountResult | None = None
    last_err: CountResult | None = None

    for i, query in enumerate(variants):
        if i:
            time.sleep(delay_s)
        result = count_for_marketplace(mp, query, session)
        if result.count is None:
            last_err = result
            continue
        tagged = CountResult(
            result.count,
            f"{result.detail} (query={query!r})",
            result.source,
        )
        if best is None or (tagged.count or 0) > (best.count or 0):
            best = tagged

    if best is not None:
        return best
    return last_err or CountResult(None, "no keyword variants produced a count", "error")


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def enabled_marketplaces(cfg: dict) -> list[dict]:
    out = []
    for mp in cfg.get("marketplaces") or []:
        if mp.get("enabled", True) is False:
            continue
        out.append(mp)
    return out


def scan(
    config_path: str,
    out_path: str,
    delay_s: float = DEFAULT_DELAY_S,
    smoke: bool = False,
) -> None:
    cfg = load_config(config_path)
    products = list(cfg.get("products") or [])
    marketplaces = enabled_marketplaces(cfg)

    if not products:
        print("ERROR: no products in config")
        sys.exit(1)
    if not marketplaces:
        print("ERROR: no enabled marketplaces in config")
        sys.exit(1)

    if smoke:
        products = products[:1]
        print(f"SMOKE mode: only product {products[0]['name']!r}")

    print(
        f"Marketplaces: {', '.join(mp.get('name', '?') for mp in marketplaces)} | "
        f"products: {len(products)} | delay: {delay_s}s"
    )

    session = requests.Session()
    rows: list[dict] = []

    for product in products:
        name = product["name"]
        keywords = product.get("keywords") or [name]
        row: dict = {"product": name}

        for mp in marketplaces:
            col = f"{mp['name']}_listing_count"
            # Max across keyword variants = true competition ceiling.
            result = best_count_for_marketplace(mp, keywords, session, delay_s)

            if result.count is None:
                row[col] = "ERR"
                print(f"  [warn] {mp['name']} / {name}: {result.detail}")
            else:
                row[col] = result.count
                print(
                    f"  {mp['name']}: {name} -> {result.count} "
                    f"[{result.source}] {result.detail}"
                )
            time.sleep(delay_s)

        rows.append(row)
        print(f"  done: {name}")

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    fieldnames = ["product"] + [f"{mp['name']}_listing_count" for mp in marketplaces]
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # Summary
    err_counts = {mp["name"]: 0 for mp in marketplaces}
    for row in rows:
        for mp in marketplaces:
            if row.get(f"{mp['name']}_listing_count") == "ERR":
                err_counts[mp["name"]] += 1
    print(f"\nWrote {len(rows)} rows to {out_path}")
    for mp_name, n_err in err_counts.items():
        if n_err:
            print(f"  [summary] {mp_name}: {n_err}/{len(rows)} ERR")
        else:
            print(f"  [summary] {mp_name}: ok ({len(rows)} products)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Scan maker marketplaces for existing listing competition."
    )
    parser.add_argument("--config", default="config/products.yaml")
    parser.add_argument("--out", default="out/marketplace_signal.csv")
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY_S,
        help=f"Seconds between marketplace requests (default {DEFAULT_DELAY_S}).",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Only scan the first product (quick adapter check).",
    )
    args = parser.parse_args()
    scan(args.config, args.out, delay_s=args.delay, smoke=args.smoke)
