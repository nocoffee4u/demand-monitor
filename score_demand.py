#!/usr/bin/env python3
"""
score_demand.py
----------------
Merges available signal CSVs into one ranked demand report. Normalizes each
raw metric to a 0-100 scale, then computes a weighted composite score.

NOTE: A full Demand vs Competition vs Opportunity overhaul is planned
(Feature 3). For now, search volume (DataForSEO) is included when
out/search_volume_signal.csv exists, and Reddit is lightly weighted so
missing/stale Reddit data does not dominate.

Composite score weights (edit WEIGHTS below to tune):
  - Search volume (Google Ads via DataForSEO): primary demand signal
  - Google Trends interest + momentum
  - Marketplace gap (low listings + interest)
  - X volume/engagement (optional)
  - Reddit volume/engagement (optional / unreliable — low weight)

USAGE:
  python3 score_demand.py
  python3 score_demand.py --reddit out/reddit_signal.csv \\
                           --trends out/trends_signal.csv \\
                           --marketplace out/marketplace_signal.csv \\
                           --search-volume out/search_volume_signal.csv \\
                           --x out/x_signal.csv \\
                           --out out/demand_report.csv
"""
from __future__ import annotations

import argparse
import os

import pandas as pd

WEIGHTS = {
    "search_volume": 0.26,  # DataForSEO Google Ads monthly volume
    "community_downloads": 0.14,  # Printables+Cults downloads (demand)
    "community_makes": 0.06,  # shared makes / prints
    "reddit_volume": 0.06,  # optional / unreliable
    "reddit_engagement": 0.04,
    "trends_interest": 0.14,
    "trends_momentum": 0.06,
    "marketplace_gap": 0.16,  # rewards LOW saturation relative to interest
    "x_volume": 0.05,
    "x_engagement": 0.03,
}


def normalize(series: pd.Series) -> pd.Series:
    if series.max() == series.min():
        return series * 0 + 50  # flat data -> neutral score
    return (series - series.min()) / (series.max() - series.min()) * 100


def _safe_read(path: str | None) -> pd.DataFrame | None:
    if not path or not os.path.exists(path):
        return None
    return pd.read_csv(path)


def _merge_on_product(base: pd.DataFrame, other: pd.DataFrame | None) -> pd.DataFrame:
    if other is None or other.empty:
        return base
    drop_cols = [c for c in other.columns if c == "category" and c in base.columns]
    other = other.drop(columns=drop_cols, errors="ignore")
    if base.empty:
        return other
    return base.merge(other, on="product", how="outer")


def _redistribute_unused(weights: dict, unused_keys: list[str]) -> dict:
    w = dict(weights)
    freed = 0.0
    for k in unused_keys:
        freed += w.pop(k, 0)
    if freed and w:
        total = sum(w.values())
        if total > 0:
            for k in list(w):
                w[k] = w[k] + freed * (w[k] / total)
    return w


def main(
    reddit_path: str,
    trends_path: str,
    marketplace_path: str,
    out_path: str,
    x_path: str | None = None,
    search_volume_path: str | None = None,
    community_path: str | None = None,
) -> None:
    # Prefer marketplace/products as the product spine when Reddit is missing.
    frames = [
        _safe_read(search_volume_path),
        _safe_read(community_path),
        _safe_read(marketplace_path),
        _safe_read(trends_path),
        _safe_read(reddit_path),
        _safe_read(x_path),
    ]
    df = pd.DataFrame()
    for fr in frames:
        df = _merge_on_product(df, fr)
    if df.empty:
        raise SystemExit("No signal CSVs found to score.")

    # Fill expected columns when a source was skipped.
    for col, default in [
        ("reddit_matching_posts", 0),
        ("reddit_total_upvotes", 0),
        ("reddit_total_comments", 0),
        ("trends_avg_interest_0_100", 0),
        ("trends_recent_vs_prior_pct_change", 0),
        ("x_matching_posts", 0),
        ("x_total_likes", 0),
        ("x_total_replies", 0),
        ("x_total_reposts", 0),
        ("search_volume", 0),
        ("community_downloads", 0),
        ("community_makes", 0),
        ("community_likes", 0),
    ]:
        if col not in df.columns:
            df[col] = default
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(default)

    marketplace_cols = [c for c in df.columns if c.endswith("_listing_count")]
    for c in marketplace_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    df["total_listings"] = df[marketplace_cols].sum(axis=1) if marketplace_cols else 0

    df["score_search_volume"] = normalize(df["search_volume"])
    df["score_community_downloads"] = normalize(df["community_downloads"])
    df["score_community_makes"] = normalize(df["community_makes"])
    df["score_reddit_volume"] = normalize(df["reddit_matching_posts"])
    df["score_reddit_engagement"] = normalize(
        df["reddit_total_upvotes"] + df["reddit_total_comments"]
    )
    df["score_trends_interest"] = normalize(df["trends_avg_interest_0_100"])
    df["score_trends_momentum"] = normalize(df["trends_recent_vs_prior_pct_change"])
    saturation_penalty = normalize(df["total_listings"])
    # Prefer search volume for the "interest" half of marketplace gap when present.
    interest_for_gap = df["score_search_volume"]
    if df["search_volume"].sum() == 0:
        interest_for_gap = df["score_trends_interest"]
    df["score_marketplace_gap"] = interest_for_gap * 0.6 + (100 - saturation_penalty) * 0.4
    df["score_x_volume"] = normalize(df["x_matching_posts"])
    df["score_x_engagement"] = normalize(
        df["x_total_likes"] + df["x_total_replies"] + df["x_total_reposts"]
    )

    weights = dict(WEIGHTS)
    unused: list[str] = []
    if df["search_volume"].sum() == 0:
        unused.append("search_volume")
    if df["community_downloads"].sum() == 0 and df["community_makes"].sum() == 0:
        unused.extend(["community_downloads", "community_makes"])
    if df["reddit_matching_posts"].sum() == 0 and (
        df["reddit_total_upvotes"] + df["reddit_total_comments"]
    ).sum() == 0:
        unused.extend(["reddit_volume", "reddit_engagement"])
    if df["x_matching_posts"].sum() == 0 and (
        df["x_total_likes"] + df["x_total_replies"] + df["x_total_reposts"]
    ).sum() == 0:
        unused.extend(["x_volume", "x_engagement"])
    if (
        df["trends_avg_interest_0_100"].sum() == 0
        and df["trends_recent_vs_prior_pct_change"].sum() == 0
    ):
        unused.extend(["trends_interest", "trends_momentum"])
    weights = _redistribute_unused(weights, unused)

    df["demand_score"] = (
        df["score_search_volume"] * weights.get("search_volume", 0)
        + df["score_community_downloads"] * weights.get("community_downloads", 0)
        + df["score_community_makes"] * weights.get("community_makes", 0)
        + df["score_reddit_volume"] * weights.get("reddit_volume", 0)
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
        "search_volume",
        "community_downloads",
        "community_makes",
        "total_listings",
        "reddit_matching_posts",
    ]
    display_cols = [c for c in display_cols if c in df.columns]
    print(df[display_cols].to_string(index=False))
    print(f"\nFull report with all metrics written to {out_path}")
    if unused:
        print(f"(Redistributed weights for empty signals: {', '.join(unused)})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reddit", default="out/reddit_signal.csv")
    parser.add_argument("--trends", default="out/trends_signal.csv")
    parser.add_argument("--marketplace", default="out/marketplace_signal.csv")
    parser.add_argument(
        "--search-volume",
        default="out/search_volume_signal.csv",
        help="DataForSEO search volume CSV (skipped if missing)",
    )
    parser.add_argument(
        "--community",
        default="out/printables_cults_signal.csv",
        help="Printables/Cults engagement CSV (skipped if missing)",
    )
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
        search_volume_path=args.search_volume,
        community_path=args.community,
    )