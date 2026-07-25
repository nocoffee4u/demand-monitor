#!/usr/bin/env python3
"""
score_demand.py
----------------
Merges reddit_signal.csv + trends_signal.csv + marketplace_signal.csv into
one ranked demand report. Normalizes each raw metric to a 0-100 scale, then
computes a weighted composite score.

Composite score weights (edit WEIGHTS below to tune):
  - Reddit conversation volume: people actively asking/complaining about it
  - Reddit engagement (upvotes+comments): how much a mention resonates
  - Google Trends interest: broader search demand outside these communities
  - Trends momentum: is interest growing or fading
  - Marketplace saturation: HIGH existing listings = validated demand but
    more competition; scored with a mild penalty, not a straight bonus,
    so a whitespace opportunity with real interest still ranks well.

USAGE:
  python3 score_demand.py --reddit out/reddit_signal.csv \\
                           --trends out/trends_signal.csv \\
                           --marketplace out/marketplace_signal.csv \\
                           --out out/demand_report.csv
"""
import argparse
import pandas as pd

WEIGHTS = {
    "reddit_volume": 0.30,
    "reddit_engagement": 0.20,
    "trends_interest": 0.25,
    "trends_momentum": 0.10,
    "marketplace_gap": 0.15,  # rewards LOW saturation relative to interest
}


def normalize(series):
    if series.max() == series.min():
        return series * 0 + 50  # flat data -> neutral score
    return (series - series.min()) / (series.max() - series.min()) * 100


def main(reddit_path, trends_path, marketplace_path, out_path):
    reddit = pd.read_csv(reddit_path)
    trends = pd.read_csv(trends_path)
    marketplace = pd.read_csv(marketplace_path)

    df = reddit.merge(trends, on="product", how="outer").merge(
        marketplace, on="product", how="outer"
    )

    df["reddit_matching_posts"] = df["reddit_matching_posts"].fillna(0)
    df["reddit_total_upvotes"] = df["reddit_total_upvotes"].fillna(0)
    df["reddit_total_comments"] = df["reddit_total_comments"].fillna(0)
    df["trends_avg_interest_0_100"] = df["trends_avg_interest_0_100"].fillna(0)
    df["trends_recent_vs_prior_pct_change"] = df[
        "trends_recent_vs_prior_pct_change"
    ].fillna(0)

    marketplace_cols = [c for c in df.columns if c.endswith("_listing_count")]
    for c in marketplace_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    df["total_listings"] = df[marketplace_cols].sum(axis=1) if marketplace_cols else 0

    df["score_reddit_volume"] = normalize(df["reddit_matching_posts"])
    df["score_reddit_engagement"] = normalize(
        df["reddit_total_upvotes"] + df["reddit_total_comments"]
    )
    df["score_trends_interest"] = normalize(df["trends_avg_interest_0_100"])
    df["score_trends_momentum"] = normalize(df["trends_recent_vs_prior_pct_change"])
    # Gap score: high interest + low existing listings scores highest.
    # Uses interest score minus a saturation penalty (capped at 0-100).
    saturation_penalty = normalize(df["total_listings"])
    df["score_marketplace_gap"] = (
        df["score_trends_interest"] * 0.6 + (100 - saturation_penalty) * 0.4
    )

    df["demand_score"] = (
        df["score_reddit_volume"] * WEIGHTS["reddit_volume"]
        + df["score_reddit_engagement"] * WEIGHTS["reddit_engagement"]
        + df["score_trends_interest"] * WEIGHTS["trends_interest"]
        + df["score_trends_momentum"] * WEIGHTS["trends_momentum"]
        + df["score_marketplace_gap"] * WEIGHTS["marketplace_gap"]
    ).round(1)

    df = df.sort_values("demand_score", ascending=False)
    df.to_csv(out_path, index=False)

    print("\n=== RANKED DEMAND REPORT ===\n")
    display_cols = [
        "product",
        "demand_score",
        "reddit_matching_posts",
        "trends_avg_interest_0_100",
        "total_listings",
    ]
    print(df[display_cols].to_string(index=False))
    print(f"\nFull report with all metrics written to {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reddit", default="out/reddit_signal.csv")
    parser.add_argument("--trends", default="out/trends_signal.csv")
    parser.add_argument("--marketplace", default="out/marketplace_signal.csv")
    parser.add_argument("--out", default="out/demand_report.csv")
    args = parser.parse_args()
    main(args.reddit, args.trends, args.marketplace, args.out)
