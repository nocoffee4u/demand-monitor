#!/usr/bin/env python3
"""
marketplace_scan.py
--------------------
Counts how many existing listings show up on maker marketplaces (Printables,
MakerWorld, etc.) for each product's keywords. A HIGH count means the design
already exists many times over (more competition, but also validates demand).
A LOW/ZERO count for a keyword you know riders want is a whitespace signal.

This is a lightweight, generic scraper: it fetches the marketplace's public
search results HTML and counts elements matching the CSS selector you set in
config/products.yaml (`result_selector`). It does NOT log in, does NOT
bypass any paywall/auth, and only reads public search pages.

LIMITATIONS / KEEP IN MIND:
  - Marketplace sites redesign their HTML periodically; if a count suddenly
    reads 0 for everything, the selector is stale — open the search URL in a
    browser, inspect a result card, and update `result_selector`.
  - Run this occasionally (e.g. weekly), not in a tight loop, and keep the
    delay between requests. Respect each site's robots.txt / ToS; if a site
    disallows automated access, drop it from config and check manually
    instead.
  - Facebook Groups are NOT included here on purpose. Meta's ToS and active
    anti-scraping measures make automated collection unreliable and
    non-compliant. See README.md for the manual weekly-check process for
    Facebook groups instead.

USAGE:
  python3 marketplace_scan.py --config config/products.yaml --out out/marketplace_signal.csv
"""
import argparse
import csv
import os
import sys
import time
import urllib.parse

import yaml
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; printshop-demand-scan/0.1; research use)"
}


def count_results(url, selector):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return None, f"HTTP {resp.status_code}"
        soup = BeautifulSoup(resp.text, "html.parser")
        matches = soup.select(selector)
        return len(matches), None
    except Exception as e:
        return None, str(e)


def scan(config_path, out_path):
    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    marketplaces = cfg.get("marketplaces", [])
    rows = []

    for product in cfg["products"]:
        name = product["name"]
        row = {"product": name}
        primary_kw = product["keywords"][0]
        encoded = urllib.parse.quote(primary_kw)

        for mp in marketplaces:
            url = mp["search_url_template"].format(query=encoded)
            count, err = count_results(url, mp["result_selector"])
            col = f"{mp['name']}_listing_count"
            row[col] = count if count is not None else "ERR"
            if err:
                print(f"  [warn] {mp['name']} lookup failed for '{name}': {err}")
            time.sleep(2)

        rows.append(row)
        print(f"  scanned: {name}")

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    fieldnames = list(rows[0].keys())
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nWrote {len(rows)} rows to {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/products.yaml")
    parser.add_argument("--out", default="out/marketplace_signal.csv")
    args = parser.parse_args()
    scan(args.config, args.out)
