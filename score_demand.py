#!/usr/bin/env python3
"""
score_demand.py
----------------
Merges reddit + trends + marketplace (+ optional X) signals into one ranked
demand report. Normalizes each raw metric to a 0-100 scale, then computes a
weighted composite score.

Composite score weights (edit WEIGHTS below to tune):
  - Reddit conversation volume: people actively asking/complaining about it
  - Reddit engagement (upvotes+comments): how much a mention resonates
  - Google Trends interest: broader search demand outside these communities
  - Trends momentum: is interest growing or fading
  - Marketplace saturation: HIGH existing listings = validated demand but
    more competition; scored with a mild penalty, not a straight bonus,
    so a whitespace opportunity with real interest still ranks well.
  - X volume/engagement: short-horizon social chatter (last ~7 days when
    using the API). Light weight by default — noisy and costly to fetch.

USAGE:
  python3 score_demand.py
  python3 score_demand.py --reddit out/reddit_signal.csv \\
                           --trends out/trends_signal.csv \\
                           --marketplace out/marketplace_signal.csv \\
                           --x out/x_signal.csv \\
                           --out out/demand_report.csv
"""
from __future__ import annotations

import argparse
import os

import pandas as pd

WEIGHTS = {
    "reddit_volume": 0.26,
    "reddit_engagement": 0.17,
    "trends_interest": 0.22,
    "trends_momentum": 0.09,
    "marketplace_gap": 0.14,  # rewards LOW saturation relative to interest
    "x_volume": 0.07,
    "x_engagement": 0.05,
}


def normalize(series: pd.Series) -> pd.Series:
    if series.max() == series.min():
        return series * 0 + 50  # flat data -> neutral score
    return (series - series.min()) / (series.max() - series.min()) * 100


def main(
    reddit_path: str,
    trends_path: str,
    marketplace_path: str,
    out_path: str,
    x_path: str | None = None,
) -> None:
    reddit = pd.read_csv(reddit_path)
    trends = pd.read_csv(trends_path)
    marketplace = pd.read_csv(marketplace_path)

    df = reddit.merge(trends, on="product", how="outer").merge(
        marketplace, on="product", how="outer"
    )

    has_x = bool(x_path and os.path.exists(x_path))
    if has_x:
        xdf = pd.read_csv(x_path)
        # Avoid duplicate category columns if present on both sides.
        drop_cols = [c for c in xdf.columns if c == "category" and c in df.columns]
        xdf = xdf.drop(columns=drop_cols, errors="ignore")
        df = df.merge(xdf, on="product", how="outer")
    else:
        df["x_matching_posts"] = 0
        df["x_total_likes"] = 0
        df["x_total_replies"] = 0
        df["x_total_reposts"] = 0

    df["reddit_matching_posts"] = df["reddit_matching_posts"].fillna(0)
    df["reddit_total_upvotes"] = df["reddit_total_upvotes"].fillna(0)
    df["reddit_total_comments"] = df["reddit_total_comments"].fillna(0)
    df["trends_avg_interest_0_100"] = df["trends_avg_interest_0_100"].fillna(0)
    df["trends_recent_vs_prior_pct_change"] = df[
        "trends_recent_vs_prior_pct_change"
    ].fillna(0)
    df["x_matching_posts"] = pd.to_numeric(
        df.get("x_matching_posts", 0), errors="coerce"
    ).fillna(0)
    df["x_total_likes"] = pd.to_numeric(
        df.get("x_total_likes", 0), errors="coerce"
    ).fillna(0)
    df["x_total_replies"] = pd.to_numeric(
        df.get("x_total_replies", 0), errors="coerce"
    ).fillna(0)
    df["x_total_reposts"] = pd.to_numeric(
        df.get("x_total_reposts", 0), errors="coerce"
    ).fillna(0)

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
    saturation_penalty = normalize(df["total_listings"])
    df["score_marketplace_gap"] = (
        df["score_trends_interest"] * 0.6 + (100 - saturation_penalty) * 0.4
    )
    df["score_x_volume"] = normalize(df["x_matching_posts"])
    df["score_x_engagement"] = normalize(
        df["x_total_likes"] + df["x_total_replies"] + df["x_total_reposts"]
    )

    # If X is entirely flat zeros, don't let neutral 50s dilute the ranking —
    # re-normalize remaining weights to sum to 1.
    weights = dict(WEIGHTS)
    x_all_zero = (
        df["x_matching_posts"].sum() == 0
        and (df["x_total_likes"] + df["x_total_replies"] + df["x_total_reposts"]).sum()
        == 0
    )
    if x_all_zero:
        x_w = weights.pop("x_volume", 0) + weights.pop("x_engagement", 0)
        if x_w and weights:
            # Redistribute X weight proportionally across remaining signals.
            total = sum(weights.values())
            for k in list(weights):
                weights[k] = weights[k] + x_w * (weights[k] / total)

    df["demand_score"] = (
        df["score_reddit_volume"] * weights.get("reddit_volume", 0)
        + df["score_reddit_engagement"] * weights.get("reddit_engagement", 0)
        + df["score_trends_interest"] * weights.get("trends_interest", 0)
        + df["score_trends_momentum"] * weights.get("trends_momentum", 0)
        + df["score_marketplace_gap"] * weights.get("marketplace_gap", 0)
        + df["score_x_volume"] * weights.get("x_volume", 0)
        + df["score_x_engagement"] * weights.get("x_engagement", 0)
    ).round(1)

    df = df.sort_values("demand_score", ascending=False)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    df.to_csv(out_path, index=False)

    print("\n=== RANKED DEMAND REPORT ===\n")
    display_cols = [
        "product",
        "demand_score",
        "reddit_matching_posts",
        "trends_avg_interest_0_100",
        "total_listings",
        "x_matching_posts",
    ]
    display_cols = [c for c in display_cols if c in df.columns]
    print(df[display_cols].to_string(index=False))
    print(f"\nFull report with all metrics written to {out_path}")
    if x_all_zero:
        print(
            "(X signal all zeros this run — X weights redistributed to other "
            "signals so they don't flatten the ranking.)"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reddit", default="out/reddit_signal.csv")
    parser.add_argument("--trends", default="out/trends_signal.csv")
    parser.add_argument("--marketplace", default="out/marketplace_signal.csv")
    parser.add_argument(
        "--x",
        default="out/x_signal.csv",
        help="Optional X signal CSV (skipped if missing)",
    )
    parser.add_argument("--out", default="out/demand_report.csv")
    args = parser.parse_args()
    main(
        args.reddit,
        args.trends,
        args.marketplace,
        args.out,
        x_path=args.x,
    )
