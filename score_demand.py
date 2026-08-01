#!/usr/bin/env python3
"""
score_demand.py
----------------
Merges signal CSVs and ranks products on three transparent scores:

  demand_score        0–100  How strong is the pull?
                       Search volume + Printables/Cults engagement +
                       Trends + X + (optional, low-weight) Reddit

  competition_score   0–100  How crowded is supply?
                       Marketplace listing counts + Google Ads competition
                       + existing-model engagement (incumbent strength)

  opportunity_score   0–100  Primary rank — demand relative to competition
                       demand / (competition + floor), then re-normalized

Empty / all-zero optional sources (Reddit, X, Trends) have their weights
redistributed so missing data does not flatten or invent signal.

USAGE:
  python3 score_demand.py
  python3 score_demand.py --out out/demand_report.csv

Edit DEMAND_WEIGHTS / COMPETITION_WEIGHTS / OPPORTUNITY_* below to tune.
"""
from __future__ import annotations

import argparse
import os
from typing import Iterable

import pandas as pd

# ---------------------------------------------------------------------------
# Weights (should each sum ~1.0; unused keys are redistributed at runtime)
# ---------------------------------------------------------------------------

DEMAND_WEIGHTS = {
    "search_volume": 0.38,  # DataForSEO Google Ads monthly volume
    "community_downloads": 0.20,  # Printables+Cults downloads
    "community_makes": 0.08,  # shared makes
    "community_likes": 0.07,  # likes / favorites
    "trends_interest": 0.12,
    "trends_momentum": 0.05,
    "x_volume": 0.04,
    "x_engagement": 0.02,
    # Reddit is optional / unreliable — near-zero; fully dropped if empty
    "reddit_volume": 0.02,
    "reddit_engagement": 0.02,
}

COMPETITION_WEIGHTS = {
    # Higher = more competition (worse for whitespace opportunities)
    "marketplace_listings": 0.65,  # printables+cults listing counts
    "ads_competition": 0.15,  # Google Ads competition_index 0–100
    "incumbent_strength": 0.20,  # high existing-model downloads = strong rivals
}

# Opportunity = demand / (competition + floor). Floor avoids divide-by-zero and
# damps tiny-competition noise. Results are re-normalized to 0–100 across the run.
OPPORTUNITY_COMPETITION_FLOOR = 12.0

# Blend: pure ratio vs "demand × whitespace". 1.0 = pure ratio only.
OPPORTUNITY_RATIO_BLEND = 0.65


def normalize(series: pd.Series) -> pd.Series:
    """Min-max to 0–100. Flat series → 50 (neutral), not 0."""
    s = pd.to_numeric(series, errors="coerce")
    if s.isna().all():
        return pd.Series([50.0] * len(series), index=series.index)
    s = s.fillna(s.median() if s.notna().any() else 0)
    lo, hi = s.min(), s.max()
    if hi == lo:
        return pd.Series([50.0] * len(s), index=s.index)
    return (s - lo) / (hi - lo) * 100.0


def _safe_read(path: str | None) -> pd.DataFrame | None:
    if not path or not os.path.exists(path):
        return None
    try:
        return pd.read_csv(path)
    except Exception as e:
        print(f"  [warn] could not read {path}: {e}")
        return None


def _merge_on_product(base: pd.DataFrame, other: pd.DataFrame | None) -> pd.DataFrame:
    if other is None or other.empty:
        return base
    drop_cols = [c for c in other.columns if c == "category" and c in base.columns]
    other = other.drop(columns=drop_cols, errors="ignore")
    if base.empty:
        return other.copy()
    return base.merge(other, on="product", how="outer")


def _redistribute(weights: dict[str, float], unused: Iterable[str]) -> dict[str, float]:
    w = dict(weights)
    freed = 0.0
    for k in unused:
        freed += w.pop(k, 0.0)
    if freed and w:
        total = sum(w.values())
        if total > 0:
            for k in list(w):
                w[k] = w[k] + freed * (w[k] / total)
    # Re-normalize to sum 1.0
    total = sum(w.values())
    if total > 0:
        w = {k: v / total for k, v in w.items()}
    return w


def _ensure_numeric(df: pd.DataFrame, cols: list[str], default: float = 0.0) -> None:
    for col in cols:
        if col not in df.columns:
            df[col] = default
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(default)


def _signal_empty(df: pd.DataFrame, cols: list[str]) -> bool:
    return all(df[c].sum() == 0 for c in cols if c in df.columns)


def main(
    reddit_path: str,
    trends_path: str,
    marketplace_path: str,
    out_path: str,
    x_path: str | None = None,
    search_volume_path: str | None = None,
    community_path: str | None = None,
) -> None:
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

    # --- Coerce raw inputs -------------------------------------------------
    _ensure_numeric(
        df,
        [
            "search_volume",
            "community_downloads",
            "community_makes",
            "community_likes",
            "trends_avg_interest_0_100",
            "trends_recent_vs_prior_pct_change",
            "reddit_matching_posts",
            "reddit_total_upvotes",
            "reddit_total_comments",
            "x_matching_posts",
            "x_total_likes",
            "x_total_replies",
            "x_total_reposts",
            "ads_competition_avg",
            "cpc_avg",
        ],
    )

    marketplace_cols = [c for c in df.columns if c.endswith("_listing_count")]
    for c in marketplace_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    df["total_listings"] = (
        df[marketplace_cols].sum(axis=1) if marketplace_cols else 0.0
    )

    # --- Normalize building blocks (0–100) ---------------------------------
    df["n_search_volume"] = normalize(df["search_volume"])
    df["n_community_downloads"] = normalize(df["community_downloads"])
    df["n_community_makes"] = normalize(df["community_makes"])
    df["n_community_likes"] = normalize(df["community_likes"])
    df["n_trends_interest"] = normalize(df["trends_avg_interest_0_100"])
    df["n_trends_momentum"] = normalize(df["trends_recent_vs_prior_pct_change"])
    df["n_reddit_volume"] = normalize(df["reddit_matching_posts"])
    df["n_reddit_engagement"] = normalize(
        df["reddit_total_upvotes"] + df["reddit_total_comments"]
    )
    df["n_x_volume"] = normalize(df["x_matching_posts"])
    df["n_x_engagement"] = normalize(
        df["x_total_likes"] + df["x_total_replies"] + df["x_total_reposts"]
    )
    df["n_marketplace_listings"] = normalize(df["total_listings"])
    # ads_competition_avg is already ~0–100 when present; empty → neutral 50
    if df["ads_competition_avg"].sum() == 0:
        df["n_ads_competition"] = 50.0
    else:
        df["n_ads_competition"] = normalize(df["ads_competition_avg"])
    # Incumbent strength: existing models already collecting downloads
    df["n_incumbent_strength"] = normalize(df["community_downloads"])

    # --- Demand weights (drop empty optional sources) ----------------------
    demand_w = dict(DEMAND_WEIGHTS)
    demand_unused: list[str] = []
    if _signal_empty(df, ["search_volume"]):
        demand_unused.append("search_volume")
    if _signal_empty(df, ["community_downloads", "community_makes", "community_likes"]):
        demand_unused.extend(
            ["community_downloads", "community_makes", "community_likes"]
        )
    if _signal_empty(
        df, ["trends_avg_interest_0_100", "trends_recent_vs_prior_pct_change"]
    ):
        demand_unused.extend(["trends_interest", "trends_momentum"])
    if _signal_empty(
        df,
        [
            "reddit_matching_posts",
            "reddit_total_upvotes",
            "reddit_total_comments",
        ],
    ):
        demand_unused.extend(["reddit_volume", "reddit_engagement"])
    if _signal_empty(
        df, ["x_matching_posts", "x_total_likes", "x_total_replies", "x_total_reposts"]
    ):
        demand_unused.extend(["x_volume", "x_engagement"])
    demand_w = _redistribute(demand_w, demand_unused)

    # Map weight key → normalized column
    demand_cols = {
        "search_volume": "n_search_volume",
        "community_downloads": "n_community_downloads",
        "community_makes": "n_community_makes",
        "community_likes": "n_community_likes",
        "trends_interest": "n_trends_interest",
        "trends_momentum": "n_trends_momentum",
        "reddit_volume": "n_reddit_volume",
        "reddit_engagement": "n_reddit_engagement",
        "x_volume": "n_x_volume",
        "x_engagement": "n_x_engagement",
    }

    # Per-signal contribution (points toward demand_score)
    demand_score = pd.Series(0.0, index=df.index)
    for key, col in demand_cols.items():
        w = demand_w.get(key, 0.0)
        contrib = df[col] * w
        df[f"contrib_demand_{key}"] = contrib.round(2)
        demand_score = demand_score + contrib
    df["demand_score"] = demand_score.round(1)

    # --- Competition weights -----------------------------------------------
    comp_w = dict(COMPETITION_WEIGHTS)
    comp_unused: list[str] = []
    if _signal_empty(df, ["total_listings"]):
        comp_unused.append("marketplace_listings")
    if _signal_empty(df, ["ads_competition_avg"]):
        comp_unused.append("ads_competition")
    if _signal_empty(df, ["community_downloads"]):
        comp_unused.append("incumbent_strength")
    comp_w = _redistribute(comp_w, comp_unused)

    comp_cols = {
        "marketplace_listings": "n_marketplace_listings",
        "ads_competition": "n_ads_competition",
        "incumbent_strength": "n_incumbent_strength",
    }
    competition_score = pd.Series(0.0, index=df.index)
    for key, col in comp_cols.items():
        w = comp_w.get(key, 0.0)
        contrib = df[col] * w
        df[f"contrib_competition_{key}"] = contrib.round(2)
        competition_score = competition_score + contrib
    df["competition_score"] = competition_score.round(1)

    # --- Opportunity -------------------------------------------------------
    # 1) Ratio: high demand / low competition
    ratio_raw = df["demand_score"] / (
        df["competition_score"] + OPPORTUNITY_COMPETITION_FLOOR
    )
    ratio_norm = normalize(ratio_raw)
    # 2) Whitespace blend: demand × (1 − competition/100)
    whitespace = df["demand_score"] * (1.0 - df["competition_score"] / 100.0)
    whitespace_norm = normalize(whitespace)

    blend = OPPORTUNITY_RATIO_BLEND
    df["opportunity_raw_ratio"] = ratio_raw.round(4)
    df["opportunity_score"] = (
        ratio_norm * blend + whitespace_norm * (1.0 - blend)
    ).round(1)

    # Rank primary key = opportunity; keep demand_score for backward compat readers
    df = df.sort_values(
        ["opportunity_score", "demand_score"], ascending=[False, False]
    )
    df.insert(0, "rank", range(1, len(df) + 1))

    # Human-readable "why" blurb
    def explain(row: pd.Series) -> str:
        parts = []
        parts.append(f"demand={row['demand_score']:.0f}")
        # top demand drivers
        d_bits = []
        for key in demand_cols:
            c = row.get(f"contrib_demand_{key}", 0) or 0
            if c >= 3:
                d_bits.append(f"{key}={c:.0f}")
        if d_bits:
            parts.append("d[" + ", ".join(d_bits[:4]) + "]")
        parts.append(f"comp={row['competition_score']:.0f}")
        c_bits = []
        for key in comp_cols:
            c = row.get(f"contrib_competition_{key}", 0) or 0
            if c >= 3:
                c_bits.append(f"{key}={c:.0f}")
        if c_bits:
            parts.append("c[" + ", ".join(c_bits) + "]")
        parts.append(f"opp={row['opportunity_score']:.0f}")
        return " | ".join(parts)

    df["score_explanation"] = df.apply(explain, axis=1)

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    df.to_csv(out_path, index=False)

    # --- Console report ----------------------------------------------------
    print("\n=== OPPORTUNITY RANKING (Demand vs Competition) ===\n")
    display = [
        "rank",
        "product",
        "opportunity_score",
        "demand_score",
        "competition_score",
        "search_volume",
        "community_downloads",
        "total_listings",
    ]
    display = [c for c in display if c in df.columns]
    print(df[display].to_string(index=False))

    print("\n=== TOP 5 — score breakdown ===\n")
    for _, row in df.head(5).iterrows():
        print(f"#{int(row['rank'])}  {row['product']}")
        print(f"    {row['score_explanation']}")
        print(
            f"    volume={int(row['search_volume']):,}  "
            f"community_dl={int(row['community_downloads']):,}  "
            f"listings={int(row['total_listings']):,}"
        )

    print(f"\nFull report written to {out_path}")
    print(
        "Sort key: opportunity_score  "
        f"(ratio blend={OPPORTUNITY_RATIO_BLEND}, "
        f"competition floor={OPPORTUNITY_COMPETITION_FLOOR})"
    )
    if demand_unused:
        print(f"Demand weights dropped (empty): {', '.join(demand_unused)}")
    if comp_unused:
        print(f"Competition weights dropped (empty): {', '.join(comp_unused)}")
    print(
        "Active demand weights: "
        + ", ".join(f"{k}={v:.2f}" for k, v in sorted(demand_w.items(), key=lambda x: -x[1]))
    )
    print(
        "Active competition weights: "
        + ", ".join(f"{k}={v:.2f}" for k, v in sorted(comp_w.items(), key=lambda x: -x[1]))
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Rank products by Demand, Competition, and Opportunity scores."
    )
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
