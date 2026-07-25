#!/usr/bin/env python3
"""
trends_scan.py
---------------
Pulls Google Trends "interest over time" for each product's keywords using
pytrends (unofficial Google Trends client). Produces a 0-100 relative
interest score and a simple trend direction (last 3 months vs prior 9).

CAVEATS (important):
  - pytrends is an *unofficial*, unmaintained wrapper (archived by its
    maintainers in 2025). It still works for light, infrequent use but Google
    may serve 429 (rate limit) errors with no documented threshold. Run this
    weekly at most, not continuously.
  - Google shipped an official Google Trends API in 2025 but it is in alpha
    with limited quota. If pytrends becomes unreliable, that's the long-term
    replacement to switch to; SerpApi's Google Trends endpoint is a paid
    fallback that abstracts the scraping/rate-limit problem for a fee if you
    want something more production-grade than pytrends.

USAGE:
  python3 trends_scan.py --config config/products.yaml --out out/trends_signal.csv
"""
import argparse
import csv
import os
import sys
import time

import yaml

try:
    from pytrends.request import TrendReq
except ImportError:
    print("Missing dependency. Run: pip install -r requirements.txt")
    sys.exit(1)


def scan(config_path, out_path):
    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    pytrends = TrendReq(hl="en-US", tz=360)
    rows = []

    for product in cfg["products"]:
        name = product["name"]
        # Google Trends comparisons work best with <=5 terms; use the top
        # 1-2 keywords per product to keep queries fast and avoid throttling.
        kws = product["keywords"][:2]
        avg_interest = 0
        recent_vs_prior_pct = None

        try:
            pytrends.build_payload(kws, timeframe="today 12-m", geo="US")
            df = pytrends.interest_over_time()
            if not df.empty:
                for col in kws:
                    if col not in df.columns:
                        continue
                series = df[[c for c in kws if c in df.columns]].mean(axis=1)
                avg_interest = round(series.mean(), 1)
                if len(series) >= 12:
                    recent = series.tail(12).mean()  # ~ last 3 months of weekly pts
                    prior = series.head(len(series) - 12).mean()
                    if prior > 0:
                        recent_vs_prior_pct = round(
                            ((recent - prior) / prior) * 100, 1
                        )
        except Exception as e:
            print(f"  [warn] trends lookup failed for '{name}': {e}")

        rows.append(
            {
                "product": name,
                "trends_avg_interest_0_100": avg_interest,
                "trends_recent_vs_prior_pct_change": recent_vs_prior_pct,
            }
        )
        print(f"  scanned: {name} -> avg interest {avg_interest}")
        time.sleep(2)  # be polite; unofficial API, no documented rate limit

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nWrote {len(rows)} rows to {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/products.yaml")
    parser.add_argument("--out", default="out/trends_signal.csv")
    args = parser.parse_args()
    scan(args.config, args.out)
