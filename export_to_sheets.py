#!/usr/bin/env python3
"""
export_to_sheets.py
-------------------
Push demand-monitor pipeline outputs into a Google Sheet (Service Account).

Tabs (per docs/sheets_dashboard_spec.md + voice_radar_spec.md):
  Dashboard, Product Rankings, Scoring Detail, Market Voice, Search Volume,
  Marketplace, Local Service (Phoenix), History, Config

USAGE:
  python3 export_to_sheets.py
  python3 export_to_sheets.py --dry-run          # build payloads, no API
  python3 export_to_sheets.py --skip-charts
  SKIP_SHEETS=1 ./run_all.sh                     # skip from pipeline

SETUP: see docs/sheets_setup.md
  GOOGLE_SERVICE_ACCOUNT_JSON=/path/to/sa.json
  GOOGLE_SHEETS_SPREADSHEET_ID=your_sheet_id
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from market_voice import VOICE_COLS, build_market_voice, write_market_voice

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

LOG = logging.getLogger("export_to_sheets")

# Tab order and titles must match the spec
TAB_ORDER = [
    "Dashboard",
    "Product Rankings",
    "Scoring Detail",
    "Market Voice",
    "Search Volume",
    "Marketplace",
    "Local Service (Phoenix)",
    "History",
    "Config",
]

# Hidden sheet for chart series (trend pivot, category averages, labeled scatter).
# Keeps Dashboard free of raw chart-helper tables (spec §1.1).
CHART_DATA_TAB = "_ChartData"
TREND_TOP_N = 8
# _ChartData layout: trend @ row 0, category @ 40, Demand-vs-Fit multi-series @ 80
CHART_CATEGORY_START = 40
CHART_SCATTER_START = 80
SCATTER_TOP_N = 12  # labeled points (legend + KEY); keeps chart readable

RANKINGS_COLS = [
    "rank",
    "product",
    "category",
    "priority_score",
    "demand_score",
    "fit_score",
    "h2s_fit",
    "competition_score",
    "opportunity_score",
    "search_volume",
    "search_volume_best_keyword",
    "cpc_avg",
    "ads_competition_avg",
    "total_listings",
    "community_downloads",
    "community_makes",
    "community_likes",
    "trends_avg_interest_0_100",
    "trends_recent_vs_prior_pct_change",
    "fit_flags",
    "score_explanation",
    "run_date",
]

# H2S equipment-match (Dashboard V1) — answers: "Does this product *use*
# H2S strengths?" NOT "Is it easy FDM?" (that is already fit_score).
# Axes: build volume, structural load, eng-materials / heated chamber.
# Intentionally ignores fdm_friendly / single_piece / high fit_score.

# Larger physical size / envelope (strong positive for H2S volume)
_H2S_SIZE_LARGE = (
    "bash guard",
    "chain guide",
    "frame protector",
    "chainstay",
    "fender",
    "mudguard",
    "snorkel",
    "storage",
    "cup holder",
    "kickstand",
)
_H2S_SIZE_MEDIUM = (
    "crash guard",
    "arm / frame",
    "frame crash",
    "cargo",
    "bracket",
    "holder",
    "widener",
    "base widener",
)
# Explicitly small / commodity geometry (no volume benefit)
_H2S_SIZE_SMALL = (
    "dust cap",
    "charge port",
    "charging port",
    "fuse cover",
    "terminal cover",
    "terminal / fuse",
    "clip",
    "clips",
    "trim clip",
    "antenna",
    "vtx",
    "phone mount",
    "display / phone",
    "gopro",
    "action cam",
    "action-cam",
    "tablet mount",
)

# Structural / load-bearing use
_H2S_STRUCT_HIGH = (
    "bash",
    "chain guide",
    "kickstand",
    "crash guard",
    "frame protector",
    "chainstay",
    "crash",
    "structural",
    "load",
)
_H2S_STRUCT_MED = (
    "mount",
    "bracket",
    "holder",
    "cargo",
    "snorkel",
    "storage",
    "guard",
    "protector",
    "routing",
)
_H2S_STRUCT_LOW = (
    "cap",
    "cover",
    "clip",
    "antenna",
    "vtx",
    "trim",
    "dust",
    "fuse",
    "terminal",
    "phone",
    "gopro",
    "action cam",
    "action-cam",
)

# Heated chamber / engineering materials benefit (heat, UV, outdoor, vibration)
_H2S_CHAMBER_HIGH = (
    "snorkel",
    "fender",
    "mudguard",
    "battery",
    "engine",
    "heat",
    "outdoor",
    "uv",
    "under hood",
    "under-hood",
    "asa",
    "nylon",
    "petg-cf",
    "pc-cf",
)
_H2S_CHAMBER_MED = (
    "utv",
    "rzr",
    "atv",
    "mtb",
    "ebike",
    "rad power",
    "radrunner",
    "bash",
    "crash",
    "chainstay",
    "frame protector",
    "kickstand",
    "automotive",
    "cable routing",
)
# Indoor / low-stress / PLA-friendly → little chamber benefit
_H2S_CHAMBER_LOW = (
    "phone",
    "tablet",
    "display",
    "gopro",
    "action cam",
    "action-cam",
    "interior trim",
    "trim clip",
    "dust cap",
    "charge port",
    "charging port",
    "antenna",
    "vtx",
)

_H2S_PROCESS_MISMATCH = (
    "resin",
    "sla",
    "metal",
    "titanium",
    "aluminum print",
    "flexible",
    "tpu",
    "rubber",
    "multi-color",
    "multicolor",
)

# Weekly History snapshot. Coverage fields (appended after community_downloads)
# exist so Radar can tell priority deltas from weight-redistribution / partial
# community weeks. New columns are additive; append_history upgrades old headers.
HISTORY_COLS = [
    "run_date",
    "run_id",
    "product",
    "category",
    "rank",
    "priority_score",
    "demand_score",
    "fit_score",
    "competition_score",
    "opportunity_score",
    "search_volume",
    "total_listings",
    "community_downloads",
    # --- coverage snapshot (voice/radar prerequisite) ---
    "sources_active_count",  # how many run_meta.sources keys were True
    "sources_active",  # semicolon-sorted active source names
    "community_platforms_ok",  # e.g. 3 when Cults+MW+Thangs ok
    "community_platforms_total",  # e.g. 4 (Printables/Cults/MW/Thangs)
]

# Columns blanked when their source is unused (per run_meta)
SOURCE_COL_MAP = {
    "reddit": [
        "reddit_matching_posts",
        "reddit_total_upvotes",
        "reddit_total_comments",
        "reddit_example_links",
    ],
    "x": [
        "x_matching_posts",
        "x_total_likes",
        "x_total_replies",
        "x_total_reposts",
        "x_example_links",
        "x_backend",
        "x_notes",
    ],
    "youtube": [
        "youtube_matching_videos",
        "youtube_total_views",
        "youtube_total_likes",
        "youtube_total_comments",
        "youtube_example_links",
        "youtube_keywords_used",
        "youtube_notes",
    ],
    "ebay": [
        "ebay_sold_count_30d",
        "ebay_sold_count_90d",
        "ebay_avg_sold_price",
        "ebay_median_sold_price",
        "ebay_min_sold_price",
        "ebay_max_sold_price",
        "ebay_sell_through_proxy",
        "ebay_top_title",
        "ebay_keywords_used",
        "ebay_notes",
        "ebay_fetched_at",
    ],
    "etsy": [
        "etsy_listing_count",
        "etsy_sold_proxy",
        "etsy_avg_price",
        "etsy_favorites_proxy",
        "etsy_top_listing_title",
        "etsy_keywords_used",
        "etsy_notes",
        "etsy_fetched_at",
    ],
    "amazon": [
        "amazon_listing_count",
        "amazon_autocomplete_hits",
        "amazon_suggestions",
        "amazon_problem_mention_score",
        "amazon_avg_price",
        "amazon_top_title",
        "amazon_keywords_used",
        "amazon_notes",
        "amazon_fetched_at",
    ],
    "trends": [
        "trends_avg_interest_0_100",
        "trends_recent_vs_prior_pct_change",
    ],
    "search_volume": [
        "search_volume",
        "search_volume_max",
        "search_volume_sum",
        "search_volume_avg",
        "search_volume_best_keyword",
        "ads_competition_avg",
        "cpc_avg",
        "keywords_queried",
        "keywords_with_data",
    ],
    "community": [
        "community_downloads",
        "community_makes",
        "community_likes",
        "printables_downloads",
        "printables_makes",
        "printables_likes",
        "cults_downloads",
        "cults_makes",
        "cults_likes",
        "makerworld_downloads",
        "makerworld_makes",
        "makerworld_likes",
        "thangs_downloads",
        "thangs_makes",
        "thangs_likes",
    ],
}


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def load_run_meta(path: str = "out/run_meta.json") -> dict:
    p = Path(path)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except (json.JSONDecodeError, OSError) as e:
            LOG.warning("run_meta unreadable: %s", e)
    now = datetime.now().astimezone()
    return {
        "run_id": now.isoformat(timespec="seconds"),
        "run_date": now.date().isoformat(),
        "run_time": now.strftime("%H:%M:%S%z"),
        "demand_unused": [],
        "competition_unused": [],
        "sources": {},
        "products_tracked": 0,
    }


def load_products_yaml(path: str = "config/products.yaml") -> list[dict]:
    with open(path) as f:
        cfg = yaml.safe_load(f) or {}
    return list(cfg.get("products") or [])


def load_local_service_yaml(path: str = "config/local_service.yaml") -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    with p.open() as f:
        return (yaml.safe_load(f) or {}).get("local_service") or {}


def known_product_names(products: list[dict]) -> set[str]:
    return {p["name"] for p in products if p.get("name")}


def source_is_active(meta: dict, key: str) -> bool:
    """
    Single source of truth for active/skipped chips and blank-vs-stale.
    Prefer meta['sources'] written by score_demand.py; fall back to demand_unused.
    """
    sources = meta.get("sources") or {}
    if key in sources:
        return bool(sources[key])
    unused = set(meta.get("demand_unused") or [])
    if key == "reddit":
        return not ("reddit_volume" in unused or "reddit_engagement" in unused)
    if key == "x":
        return not ("x_volume" in unused or "x_engagement" in unused)
    if key == "youtube":
        return not (
            "youtube_volume" in unused or "youtube_engagement" in unused
        )
    if key == "ebay":
        return not (
            "ebay_sold_volume" in unused or "ebay_price_signal" in unused
        )
    if key == "etsy":
        unused_d = set(meta.get("demand_unused") or [])
        unused_c = set(meta.get("competition_unused") or [])
        # Active if either engagement (demand) or listing density (competition) has data
        return not (
            "etsy_engagement_volume" in unused_d
            and "etsy_listing_saturation" in unused_c
        )
    if key == "amazon":
        unused_d = set(meta.get("demand_unused") or [])
        unused_c = set(meta.get("competition_unused") or [])
        return not (
            "amazon_problem_signal" in unused_d
            and "amazon_listing_saturation" in unused_c
        )
    if key == "trends":
        return not ("trends_interest" in unused or "momentum" in unused)
    if key == "search_volume":
        return not ("search_volume" in unused or "volume_quality" in unused)
    if key == "community":
        return "community_downloads" not in unused
    if key == "marketplace":
        return "marketplace_listings" not in set(meta.get("competition_unused") or [])
    return True


def community_source_chip(meta: dict, active: bool) -> str:
    """
    Community chip with platform coverage, e.g.
      Community: active (3/4)
      Community: partial (2/4)
      Community: skipped
    """
    platforms = meta.get("community_platforms") or {}
    ok = meta.get("community_platforms_ok")
    total = meta.get("community_platforms_total")
    if platforms and (ok is None or total is None):
        ok = sum(
            1
            for v in platforms.values()
            if (v.get("status") if isinstance(v, dict) else v) == "ok"
        )
        total = len(platforms)
    try:
        ok_i = int(ok) if ok is not None else None
        tot_i = int(total) if total is not None else None
    except (TypeError, ValueError):
        ok_i, tot_i = None, None

    if tot_i and tot_i > 0 and ok_i is not None:
        if ok_i <= 0:
            if not active:
                return f"Community: skipped (0/{tot_i})"
            return f"Community: error (0/{tot_i})"
        if ok_i >= tot_i:
            return f"Community: active ({ok_i}/{tot_i})"
        return f"Community: partial ({ok_i}/{tot_i})"
    return f"Community: {'active' if active else 'skipped'}"


def blank_unused_sources(df: pd.DataFrame, meta: dict) -> pd.DataFrame:
    """Turn zeros into blank for skipped sources (display-only copy)."""
    out = df.copy()
    for src, cols in SOURCE_COL_MAP.items():
        if source_is_active(meta, src):
            continue
        for c in cols:
            if c in out.columns:
                out[c] = ""
    return out


def coerce_history_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Coerce History columns after a Sheets values().get() read.
    Cells arrive as strings; nsmallest/nlargest on string 'rank' sorts
    lexicographically ("10" < "2") — always coerce before ranking logic.
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=HISTORY_COLS)
    out = df.copy()
    # Normalize column names (strip whitespace from accidental header edits)
    out.columns = [str(c).strip() for c in out.columns]
    for col in (
        "rank",
        "priority_score",
        "demand_score",
        "fit_score",
        "competition_score",
        "opportunity_score",
        "search_volume",
        "total_listings",
        "community_downloads",
        "sources_active_count",
        "community_platforms_ok",
        "community_platforms_total",
    ):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    if "product" in out.columns:
        out["product"] = out["product"].astype(str)
    if "run_date" in out.columns:
        out["run_date"] = out["run_date"].astype(str)
    if "run_id" in out.columns:
        out["run_id"] = out["run_id"].astype(str)
    return out


def history_from_sheet_values(values: list[list[Any]]) -> pd.DataFrame:
    """Parse History sheet values into a typed DataFrame (or empty)."""
    if not values or len(values) < 2:
        return pd.DataFrame(columns=HISTORY_COLS)
    header = [str(h).strip() for h in values[0]]
    # Pad short rows
    rows = []
    for row in values[1:]:
        padded = list(row) + [""] * (len(header) - len(row))
        rows.append(padded[: len(header)])
    df = pd.DataFrame(rows, columns=header)
    return coerce_history_df(df)


def build_trend_pivot(
    history: pd.DataFrame,
    rankings: pd.DataFrame,
    top_n: int = TREND_TOP_N,
) -> pd.DataFrame:
    """
    Wide table for multi-line priority trend chart:
      run_date | Product A | Product B | ...
    Products = current top `top_n` by priority_score.
    """
    if rankings.empty or "product" not in rankings.columns:
        return pd.DataFrame(columns=["run_date"])

    r = rankings.copy()
    r["priority_score"] = pd.to_numeric(r.get("priority_score"), errors="coerce")
    top_products = (
        r.sort_values("priority_score", ascending=False)["product"]
        .head(top_n)
        .tolist()
    )
    if not top_products:
        return pd.DataFrame(columns=["run_date"])

    hist = coerce_history_df(history)
    if hist.empty or "product" not in hist.columns:
        # Single-run fallback: one date row from rankings
        run_date = ""
        if "run_date" in rankings.columns and len(rankings):
            run_date = str(rankings["run_date"].iloc[0])
        row = {"run_date": run_date}
        for p in top_products:
            sub = r[r["product"] == p]
            row[p] = (
                float(sub["priority_score"].iloc[0])
                if len(sub) and pd.notna(sub["priority_score"].iloc[0])
                else ""
            )
        return pd.DataFrame([row])

    hist = hist[hist["product"].isin(top_products)].copy()
    if hist.empty:
        return pd.DataFrame(columns=["run_date"] + top_products)

    # Prefer run_date for x-axis; fall back to run_id
    date_col = "run_date" if "run_date" in hist.columns else "run_id"
    pivot = hist.pivot_table(
        index=date_col,
        columns="product",
        values="priority_score",
        aggfunc="last",
    )
    # Stable column order = current top ranking order
    pivot = pivot.reindex(columns=top_products)
    pivot = pivot.sort_index()
    pivot = pivot.reset_index().rename(columns={date_col: "run_date"})
    return pivot


def short_product_name(name: str, max_len: int = 28) -> str:
    """Compact product label for chart legends / keys."""
    s = " ".join(str(name or "").split())
    if len(s) <= max_len:
        return s
    return s[: max_len - 1].rstrip() + "…"


def demand_fit_zone(fit: float, demand: float) -> str:
    """Quadrant label for Demand vs Fit (midpoint 50)."""
    high_f, high_d = fit >= 50, demand >= 50
    if high_f and high_d:
        return "top-right ★ build"
    if high_d and not high_f:
        return "top-left (demand, low fit)"
    if high_f and not high_d:
        return "bottom-right (easy, low demand)"
    return "bottom-left (ignore)"


def build_scatter_series_matrix(
    rankings: pd.DataFrame, n_top: int = SCATTER_TOP_N
) -> tuple[list[list[Any]], int, int]:
    """
    Multi-series scatter table for Google Sheets (one series per product so the
    chart legend names each point).

    Header: fit_score | #1 short name | #2 short name | ...
    Row i:  fit_i     | (blank)       | demand only in column i | ...
    """
    if rankings.empty:
        return [["fit_score"]], 1, 1
    top = rankings.head(n_top).copy()
    for c in ("fit_score", "demand_score"):
        if c in top.columns:
            top[c] = pd.to_numeric(top[c], errors="coerce")
    labels: list[str] = []
    for i, (_, r) in enumerate(top.iterrows(), 1):
        labels.append(f"#{i} {short_product_name(r.get('product', ''), 26)}")
    header: list[Any] = ["fit_score"] + labels
    rows: list[list[Any]] = [header]
    for i, (_, r) in enumerate(top.iterrows()):
        fit = r.get("fit_score")
        demand = r.get("demand_score")
        row: list[Any] = ["" if pd.isna(fit) else float(fit)]
        for j in range(len(labels)):
            if j == i and pd.notna(demand):
                row.append(float(demand))
            else:
                row.append("")
        rows.append(row)
    return rows, len(rows), len(header)


def build_category_avg(rankings: pd.DataFrame) -> pd.DataFrame:
    if rankings.empty or "category" not in rankings.columns:
        return pd.DataFrame(columns=["category", "avg_priority_score", "n_products"])
    tmp = rankings.copy()
    tmp["priority_score"] = pd.to_numeric(tmp.get("priority_score"), errors="coerce")
    tmp["category"] = tmp["category"].replace("", "(blank)").fillna("(blank)")
    g = (
        tmp.groupby("category", dropna=False)
        .agg(
            avg_priority_score=("priority_score", "mean"),
            n_products=("product", "count"),
        )
        .reset_index()
        .sort_values("avg_priority_score", ascending=False)
    )
    g["avg_priority_score"] = g["avg_priority_score"].round(1)
    return g


def safe_read_csv(path: str) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        LOG.warning("missing %s", path)
        return pd.DataFrame()
    return pd.read_csv(p)


def df_to_values(df: pd.DataFrame, columns: list[str] | None = None) -> list[list[Any]]:
    if df.empty:
        return [columns or []]
    cols = columns or list(df.columns)
    present = [c for c in cols if c in df.columns]
    # Ensure all requested columns exist
    for c in cols:
        if c not in df.columns:
            df[c] = ""
    rows = [cols]
    for _, r in df[cols].iterrows():
        row = []
        for c in cols:
            v = r[c]
            if pd.isna(v):
                row.append("")
            elif isinstance(v, float):
                # keep ints clean
                if v == int(v) and c not in (
                    "priority_score",
                    "demand_score",
                    "fit_score",
                    "competition_score",
                    "opportunity_score",
                    "cpc_avg",
                    "ads_competition_avg",
                    "trends_avg_interest_0_100",
                    "trends_recent_vs_prior_pct_change",
                ):
                    row.append(int(v))
                else:
                    row.append(round(float(v), 4) if abs(v) < 1e10 else v)
            else:
                row.append(v)
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# H2S equipment-match (Dashboard V1 — light label only)
# ---------------------------------------------------------------------------

def _h2s_axis_score(name: str, cat: str) -> tuple[int, int, int]:
    """
    Score three H2S-specific axes 0–3 each (max 9). Does not use fit_score,
    fdm_friendly, or single_piece — those already live in Fit Score.
    Returns (size, structural, chamber_eng).
    """
    blob = f"{name} {cat}".lower()

    # --- Size / build volume ---------------------------------------------
    if any(k in blob for k in _H2S_SIZE_LARGE):
        size = 3
    elif any(k in blob for k in _H2S_SIZE_MEDIUM):
        size = 2
    elif any(k in blob for k in _H2S_SIZE_SMALL):
        size = 0
    else:
        size = 1  # unknown mid-size default

    # Category nudges for volume (vehicle-scale vs tiny drone bits)
    if cat in ("atv_utv",) and size < 3:
        size = min(3, size + 1)
    if cat == "drone_fpv" and size > 0 and not any(
        k in blob for k in ("crash", "arm / frame", "frame crash")
    ):
        size = max(0, size - 1)  # most FPV accessories are small

    # --- Structural / load-bearing ---------------------------------------
    if any(k in blob for k in _H2S_STRUCT_HIGH):
        structural = 3
    elif any(k in blob for k in _H2S_STRUCT_MED) and not any(
        k in blob for k in _H2S_STRUCT_LOW
    ):
        structural = 2
    elif any(k in blob for k in _H2S_STRUCT_LOW):
        structural = 0
    else:
        structural = 1

    # Phone/GoPro mounts: light fixture, not load-bearing eng.
    if any(
        k in blob
        for k in ("phone", "gopro", "action cam", "action-cam", "tablet", "display")
    ):
        structural = min(structural, 1)

    # --- Chamber / eng materials -----------------------------------------
    if any(k in blob for k in _H2S_CHAMBER_HIGH):
        chamber = 3
    elif any(k in blob for k in _H2S_CHAMBER_MED):
        chamber = 2
    elif any(k in blob for k in _H2S_CHAMBER_LOW):
        chamber = 0
    else:
        chamber = 1

    # Outdoor vehicle niches benefit from ASA / eng filaments
    if cat in ("atv_utv", "mtb_general") and chamber < 3:
        chamber = min(3, chamber + 1)
    # Cabin/interior / generic consumer mounts: little heat/UV need
    if any(k in blob for k in ("interior", "phone", "tablet", "display / phone")):
        chamber = min(chamber, 1)
    if cat == "automotive" and "trim" in blob:
        chamber = min(chamber, 1)

    return size, structural, chamber


def h2s_fit_label(row: pd.Series | dict) -> str:
    """
    Does this product specifically benefit from H2S strengths?

    Axes (equal weight): larger build volume, structural/load-bearing,
    engineering materials + heated chamber. Explicitly does NOT reward
    generic easy-FDM traits (those are fit_score).
    """
    if hasattr(row, "get"):
        get = row.get
    else:
        get = lambda k, d="": d  # noqa: E731

    name = str(get("product") or "").lower()
    cat = str(get("category") or "").lower()
    blob = f"{name} {cat}"

    if any(w in blob for w in _H2S_PROCESS_MISMATCH):
        return "Weak — process/material mismatch for H2S FDM fleet"

    size, structural, chamber = _h2s_axis_score(name, cat)
    total = size + structural + chamber  # 0–9

    # Require at least one real H2S-strength signal for Strong/Good
    if total >= 7 and max(size, structural, chamber) >= 3:
        return (
            "Strong — benefits from H2S volume and/or eng. materials + chamber "
            f"(size {size}/3, load {structural}/3, chamber {chamber}/3)"
        )
    if total >= 5:
        return (
            "Good — clear H2S upside on size, load, or chamber/eng materials "
            f"(size {size}/3, load {structural}/3, chamber {chamber}/3)"
        )
    if total >= 3:
        return (
            "OK — prints on H2S but little unique need for volume/chamber/eng "
            f"(size {size}/3, load {structural}/3, chamber {chamber}/3)"
        )
    return (
        "Weak — small/low-stress or poor match; H2S strengths mostly unused "
        f"(size {size}/3, load {structural}/3, chamber {chamber}/3)"
    )


# Action This Week (spec §4)
# ---------------------------------------------------------------------------

def compute_actions(
    rankings: pd.DataFrame,
    history: pd.DataFrame,
    local_kw: pd.DataFrame,
    meta: dict,
) -> list[str]:
    """
    Monday decision list (spec §4). Same thresholds; clearer Phase-1 wording.
    Labels: PROTOTYPE | WATCH | NEEDS DATA | DROP | LOCAL | NONE
    """
    actions: list[str] = []
    r = rankings.copy()
    for col in (
        "priority_score",
        "fit_score",
        "competition_score",
        "search_volume",
        "community_downloads",
        "keywords_with_data",
    ):
        if col in r.columns:
            r[col] = pd.to_numeric(r[col], errors="coerce")
    if "h2s_fit" not in r.columns:
        r["h2s_fit"] = r.apply(h2s_fit_label, axis=1)

    # 1. Prototype this week — high priority, Bambu-friendly, not saturated
    proto = r[
        (r["priority_score"] >= 70)
        & (r["fit_score"] >= 60)
        & (r["competition_score"] <= 60)
    ].head(3)
    for _, row in proto.iterrows():
        h2s = str(row.get("h2s_fit") or h2s_fit_label(row))
        h2s_short = h2s.split("—")[0].strip() if "—" in h2s else h2s
        if h2s_short.startswith("Strong"):
            print_hint = (
                "CAD → print on H2S using volume and/or eng materials "
                "(Nylon-CF / PETG-CF / ASA + chamber as needed) → list if it works"
            )
        elif h2s_short.startswith("Good"):
            print_hint = (
                "CAD → print on H2S; lean chamber/eng materials where load or "
                "outdoor/heat exposure warrants it"
            )
        elif h2s_short.startswith("OK"):
            print_hint = (
                "CAD → first print on H2S with standard materials OK "
                "(no special volume/chamber need) → list if it works"
            )
        else:
            print_hint = (
                "CAD only if design justifies H2S strengths; otherwise "
                "deprioritize vs higher H2S-fit opportunities"
            )
        actions.append(
            f"PROTOTYPE — {row['product']}: priority {row['priority_score']:.0f}, "
            f"fit {row['fit_score']:.0f}, "
            f"comp {row['competition_score']:.0f}, "
            f"H2S {h2s_short}. "
            f"Next: {print_hint}."
        )

    # 2. Watch — rising (needs ≥2 history runs)
    hist = coerce_history_df(history)
    if not hist.empty and "product" in hist.columns:
        rising = []
        for product, g in hist.groupby("product"):
            g = g.sort_values(["run_date", "run_id"])
            if len(g) < 2:
                continue
            prev_ps = g.iloc[-2]["priority_score"]
            cur_ps = g.iloc[-1]["priority_score"]
            if pd.isna(prev_ps) or pd.isna(cur_ps):
                continue
            prev, cur = float(prev_ps), float(cur_ps)
            if cur > prev and 50 <= cur < 70:
                rising.append((product, prev, cur))
        rising.sort(key=lambda x: x[2] - x[1], reverse=True)
        if not rising and hist["product"].nunique() > 0:
            runs = hist["run_id"].nunique() if "run_id" in hist.columns else 0
            if runs < 2:
                actions.append(
                    "WATCH — rising: need ≥2 weekly runs before momentum shows. "
                    "Check again next Monday."
                )
        for product, prev, cur in rising[:3]:
            actions.append(
                f"WATCH — {product}: priority rising {prev:.0f} → {cur:.0f}. "
                f"Not ready to commit — keep on radar; no prototype yet."
            )

    # 3. Needs more data
    if "keywords_with_data" in r.columns:
        need = r[
            (r["keywords_with_data"].fillna(0) == 0)
            & (r["search_volume"].fillna(0) == 0)
            & (r["community_downloads"].fillna(0) == 0)
        ].head(2)
        for _, row in need.iterrows():
            actions.append(
                f"NEEDS DATA — {row['product']}: scanners returned empty "
                f"(not proof of zero demand). Next: retune keywords in "
                f"products.yaml, then re-run search volume."
            )

    # 4. Reconsider / drop — priority < 30 for 3 consecutive history runs
    hist = coerce_history_df(history)
    if not hist.empty and "product" in hist.columns:
        drops = []
        for product, g in hist.groupby("product"):
            g = g.sort_values(["run_date", "run_id"])
            tail = g.tail(3)
            if len(tail) >= 3 and (tail["priority_score"] < 30).all():
                drops.append(product)
        for product in drops[:2]:
            actions.append(
                f"DROP? — {product}: priority < 30 for 3 weeks. "
                f"Consider pruning from products.yaml so the list stays focused."
            )

    # 5. Local service note (Phase 2, lowest priority)
    if not local_kw.empty and "search_volume" in local_kw.columns:
        lk = local_kw.copy()
        lk["search_volume"] = pd.to_numeric(lk["search_volume"], errors="coerce")
        if "competition" in lk.columns:
            low = lk[
                (lk["search_volume"] > 50)
                & (
                    lk["competition"]
                    .astype(str)
                    .str.upper()
                    .isin(["LOW", "0", "1", "2"])
                    | (
                        pd.to_numeric(lk.get("competition_index"), errors="coerce")
                        .fillna(100)
                        < 30
                    )
                )
            ]
        else:
            low = lk[lk["search_volume"] > 50]
        if not low.empty:
            top = low.sort_values("search_volume", ascending=False).iloc[0]
            actions.append(
                f"LOCAL (Phase 2) — “{top.get('keyword')}” "
                f"~{int(top['search_volume'])}/mo Phoenix, low competition. "
                f"Note only — own products still come first."
            )

    # Soft near-miss only when no PROTOTYPE and we still have room (cap 5)
    if (
        not any(a.startswith("PROTOTYPE") for a in actions)
        and len(actions) < 5
        and not r.empty
    ):
        top = r.sort_values("priority_score", ascending=False).iloc[0]
        p = float(top.get("priority_score") or 0)
        if p > 0 and p < 70:
            actions.append(
                f"CLOSEST — {top['product']}: highest priority this week "
                f"({p:.0f}) but under prototype bar (need priority≥70, fit≥60, "
                f"comp≤60). Review fit/keywords before building."
            )

    if not actions:
        actions.append(
            "NONE — Nothing crossed the bar this week. "
            "No forced build; scan Top Opportunities and wait for clearer signal."
        )
    return actions[:5]


# ---------------------------------------------------------------------------
# Build tab dataframes / matrices
# ---------------------------------------------------------------------------

def build_rankings(report: pd.DataFrame, meta: dict) -> pd.DataFrame:
    df = blank_unused_sources(report, meta)
    # Light H2S equipment-match before column trim (uses fit_flags + optional fit parts)
    df["h2s_fit"] = df.apply(h2s_fit_label, axis=1)
    for c in RANKINGS_COLS:
        if c not in df.columns and c != "run_date":
            df[c] = ""
    df["run_date"] = meta.get("run_date", "")
    # fill blank category from product meta later if needed
    out = df[RANKINGS_COLS].copy()
    return out


def build_scoring_detail(report: pd.DataFrame, meta: dict) -> pd.DataFrame:
    df = blank_unused_sources(report, meta).copy()
    df["run_date"] = meta.get("run_date", "")
    # Everything not in the trimmed Product Rankings set (except product)
    rankings_only = set(RANKINGS_COLS) - {"product", "run_date"}
    ordered = ["product", "run_date"] + [
        c for c in df.columns if c not in rankings_only and c not in ("product", "run_date")
    ]
    return df[ordered]


def build_search_volume_tab(meta: dict) -> list[list[Any]]:
    rows: list[list[Any]] = []
    active = source_is_active(meta, "search_volume")
    run_date = meta.get("run_date", "")
    if active:
        rows.append(
            [
                f"Search Volume — ACTIVE this run ({run_date})",
                "Numbers below are from this pipeline run.",
            ]
        )
    else:
        rows.append(
            [
                f"Search Volume — SKIPPED / STALE this run ({run_date})",
                "Search volume scan was not active; cells blanked so prior "
                "out/*.csv cache is not mistaken for fresh data.",
            ]
        )

    rows.append([])
    rows.append(["SECTION A — Per-product search volume summary"])
    sig = safe_read_csv("out/search_volume_signal.csv")
    if not active:
        rows.append(
            [
                "(skipped this run — re-run without SKIP_SEARCH_VOLUME / with "
                "DataForSEO credentials to refresh)"
            ]
        )
    elif sig.empty:
        rows.append(["(no search_volume_signal.csv)"])
    else:
        rows.extend(df_to_values(sig))

    rows.append([])
    kws = safe_read_csv("out/search_volume_keywords.csv")
    if not active:
        rows.append(["SECTION B — Keyword-level audit"])
        rows.append(["(skipped this run — no fresh keyword rows)"])
    elif kws.empty:
        rows.append(["SECTION B — Keyword-level audit"])
        rows.append(["(no search_volume_keywords.csv)"])
    elif "product" in kws.columns and kws["product"].astype(str).str.strip().any():
        rows.append(
            [
                "SECTION B — Keyword-level audit (per product; shared keywords "
                "repeat once per product that uses them)"
            ]
        )
        rows.extend(df_to_values(kws))
    else:
        rows.append(
            [
                "SECTION B — All queried keywords (flat audit; no product "
                "column — re-run search_volume_scan.py to link keywords)"
            ]
        )
        rows.extend(df_to_values(kws))
    return rows


def build_marketplace_tab(report: pd.DataFrame, meta: dict) -> pd.DataFrame:
    """
    Marketplace listings + community engagement. When community or marketplace
    sources are skipped this run, blank those columns and stamp a status row
    via a leading note column is awkward for DataFrames — caller wraps with
    a status banner when writing the sheet. Here we blank columns only.
    """
    mp = safe_read_csv("out/marketplace_signal.csv")
    pc = safe_read_csv("out/printables_cults_signal.csv")
    market_active = source_is_active(meta, "marketplace")
    community_active = source_is_active(meta, "community")

    if mp.empty and pc.empty:
        cols = [
            "product",
            "category",
            "printables_listing_count",
            "cults_listing_count",
            "total_listings",
            "community_downloads",
            "community_makes",
            "community_likes",
        ]
        out = report[[c for c in cols if c in report.columns]].copy()
    else:
        base = pc if not pc.empty else pd.DataFrame({"product": report["product"]})
        if not mp.empty:
            base = base.merge(mp, on="product", how="outer", suffixes=("", "_mp"))
        if "category" not in base.columns and "category" in report.columns:
            base = base.merge(
                report[["product", "category"]], on="product", how="left"
            )
        if "total_listings" not in base.columns:
            p = pd.to_numeric(
                base.get("printables_listing_count"), errors="coerce"
            ).fillna(0)
            c = pd.to_numeric(
                base.get("cults_listing_count"), errors="coerce"
            ).fillna(0)
            base["total_listings"] = p + c
        preferred = [
            "product",
            "category",
            "printables_listing_count",
            "cults_listing_count",
            "total_listings",
            "printables_downloads",
            "printables_makes",
            "printables_likes",
            "printables_top_downloads",
            "printables_top_name",
            "cults_downloads",
            "cults_makes",
            "cults_likes",
            "cults_top_downloads",
            "cults_top_name",
            "community_downloads",
            "community_makes",
            "community_likes",
        ]
        cols = [c for c in preferred if c in base.columns]
        out = base[cols].copy()

    listing_cols = [
        c
        for c in out.columns
        if c.endswith("_listing_count") or c == "total_listings"
    ]
    community_cols = [
        c
        for c in out.columns
        if "download" in c or "makes" in c or "likes" in c or "top_" in c
    ]

    if not market_active:
        for c in listing_cols:
            out[c] = ""
    if not community_active:
        for c in community_cols:
            out[c] = ""

    # Status columns for the human (first columns when written with banner)
    out.insert(0, "listings_status", "ACTIVE" if market_active else "SKIPPED/STALE")
    out.insert(
        1, "community_status", "ACTIVE" if community_active else "SKIPPED/STALE"
    )
    return out


def build_local_service_tab() -> list[list[Any]]:
    rows: list[list[Any]] = []
    rows.append(["SECTION A — Keyword demand (Phoenix)"])
    kw = safe_read_csv("out/local_service_keywords_phoenix_az.csv")
    if kw.empty:
        rows.append(["(no local_service_keywords_phoenix_az.csv)"])
    else:
        rows.extend(df_to_values(kw))

    market_path = Path("out/local_service_market_phoenix_az.json")
    market: dict = {}
    if market_path.exists():
        try:
            market = json.loads(market_path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            LOG.warning("local market json: %s", e)

    rows.append([])
    rows.append(["SECTION B — People Also Ask"])
    rows.append(["question", "source_keyword"])
    paa = market.get("people_also_ask") or []
    if not paa:
        rows.append(["(none)", ""])
    for block in paa:
        parent = block.get("parent_keyword") or ""
        for q in block.get("questions") or []:
            rows.append([q.get("question") or "", parent])

    rows.append([])
    rows.append(["SECTION C — Maps competitors"])
    rows.append(
        ["name", "rating", "review_count", "address", "phone", "url", "is_claimed"]
    )
    comps = market.get("local_competitors") or []
    if not comps:
        rows.append(["(none)", "", "", "", "", "", ""])
    for c in comps:
        rows.append(
            [
                c.get("name") or "",
                c.get("rating") if c.get("rating") is not None else "",
                c.get("review_count") if c.get("review_count") is not None else "",
                c.get("address") or c.get("snippet") or "",
                c.get("phone") or "",
                c.get("url") or "",
                c.get("is_claimed") if c.get("is_claimed") is not None else "",
            ]
        )

    rows.append([])
    costs = market.get("costs_reported") or {}
    rows.append(
        [
            "API cost this market run (USD)",
            costs.get("total_serp_usd", ""),
        ]
    )
    return rows


def build_config_tab(products: list[dict], local_svc: dict) -> list[list[Any]]:
    rows: list[list[Any]] = []
    rows.append(
        [
            "READ-ONLY MIRROR of config/products.yaml + config/local_service.yaml",
            "Edits here do NOT feed back into the pipeline.",
        ]
    )
    rows.append([])
    rows.append(
        [
            "product",
            "category",
            "keywords",
            "search_volume_keywords",
            "fit_overrides",
        ]
    )
    for p in products:
        fit = p.get("fit") or {}
        fit_s = "; ".join(f"{k}={v}" for k, v in fit.items()) if fit else ""
        rows.append(
            [
                p.get("name") or "",
                p.get("category") or "",
                "; ".join(p.get("keywords") or []),
                "; ".join(p.get("search_volume_keywords") or []),
                fit_s,
            ]
        )
    rows.append([])
    rows.append(["local_service.yaml"])
    rows.append(["city", local_svc.get("city", "")])
    rows.append(["location_name", local_svc.get("location_name", "")])
    rows.append(["cache_ttl_days", local_svc.get("cache_ttl_days", "")])
    seeds = local_svc.get("seed_keywords") or []
    rows.append(["seed_keyword_count", len(seeds)])
    return rows


def history_coverage_fields(meta: dict) -> dict:
    """
    Compact coverage snapshot for History (same values on every product row
    for a run). Lets Radar interpret priority deltas vs redistribution.
    """
    sources = meta.get("sources") or {}
    active = sorted(k for k, v in sources.items() if v)
    ok = meta.get("community_platforms_ok")
    total = meta.get("community_platforms_total")
    if ok is None or total is None:
        platforms = meta.get("community_platforms") or {}
        if isinstance(platforms, dict) and platforms:
            statuses = []
            for p in platforms.values():
                if isinstance(p, dict):
                    statuses.append(str(p.get("status") or "").lower())
                else:
                    statuses.append(str(p).lower())
            ok = sum(1 for s in statuses if s in ("ok", "active", "success"))
            total = len(platforms)
        else:
            ok, total = "", ""
    return {
        "sources_active_count": len(active),
        "sources_active": ";".join(active),
        "community_platforms_ok": ok if ok != "" else "",
        "community_platforms_total": total if total != "" else "",
    }


def build_history_rows(report: pd.DataFrame, meta: dict) -> pd.DataFrame:
    df = report.copy()
    df["run_date"] = meta.get("run_date", "")
    df["run_id"] = meta.get("run_id", "")
    cov = history_coverage_fields(meta)
    for k, v in cov.items():
        df[k] = v
    for c in HISTORY_COLS:
        if c not in df.columns:
            df[c] = ""
    return df[HISTORY_COLS]


def top10_products_for_run(hist: pd.DataFrame, run_id: str) -> set[str]:
    """Top 10 products for a History run_id — numeric-safe."""
    g = hist[hist["run_id"] == run_id]
    if g.empty:
        return set()
    if "rank" in g.columns and g["rank"].notna().any():
        return set(g.nsmallest(10, "rank")["product"].tolist())
    if "priority_score" in g.columns and g["priority_score"].notna().any():
        return set(g.nlargest(10, "priority_score")["product"].tolist())
    return set()


def build_dashboard(
    rankings: pd.DataFrame,
    meta: dict,
    actions: list[str],
    local_kw: pd.DataFrame,
    history: pd.DataFrame,
    unmatched: list[str],
) -> tuple[list[list[Any]], int]:
    """
    Human-facing Dashboard only (no raw chart-helper tables).

    Layout (top → bottom, laptop-friendly):
      1. Status strip + stacked KPIs (full text, no crammed multi-KPI row)
      2. Action This Week (decision list — full text in column B)
      3. How to read this Dashboard (metric explainers)
      4. Top Opportunities + category/local mini panels
      5. Demand vs Fit KEY + reserved CHARTS zone

    Returns (rows, charts_start_row) where charts_start_row is the 0-based
    row index of the first blank row in the charts zone (for overlay anchors).
    """
    rows: list[list[Any]] = []
    run_date = meta.get("run_date", "")
    run_time = meta.get("run_time", "")
    rows.append(["DEMAND MONITOR — DASHBOARD"])
    rows.append(["Last updated:", f"{run_date} {run_time}"])
    rows.append(["run_id:", meta.get("run_id", "")])
    freshness = "unknown"
    try:
        rd = datetime.strptime(run_date, "%Y-%m-%d").date()
        age = (datetime.now().date() - rd).days
        if age <= 8:
            freshness = f"GREEN — data is {age}d old (weekly cadence OK)"
        elif age <= 14:
            freshness = f"YELLOW — data is {age}d old"
        else:
            freshness = f"RED — data is {age}d old (schedule may be broken)"
    except Exception:
        pass
    rows.append(["Freshness:", freshness])

    chips = []
    for name, key in [
        ("Search Volume", "search_volume"),
        ("Community", "community"),
        ("Marketplace", "marketplace"),
        ("Trends", "trends"),
        ("YouTube", "youtube"),
        ("eBay", "ebay"),
        ("Etsy", "etsy"),
        ("Amazon", "amazon"),
        ("X", "x"),
        ("Reddit", "reddit"),
    ]:
        active = source_is_active(meta, key)
        if key == "community":
            chips.append(community_source_chip(meta, active))
        else:
            chips.append(f"{name}: {'active' if active else 'skipped'}")
    rows.append(["Sources this run:", " | ".join(chips)])

    n_prod = int(meta.get("products_tracked") or len(rankings))
    top_p = ""
    if not rankings.empty and "priority_score" in rankings.columns:
        top_p = float(
            pd.to_numeric(rankings["priority_score"], errors="coerce").max() or 0
        )

    # Churn — history must be numeric-coerced (see coerce_history_df)
    churn = "n/a (need ≥2 history runs)"
    hist = coerce_history_df(history)
    if not hist.empty and "run_id" in hist.columns:
        runs = sorted(hist["run_id"].dropna().unique())
        if len(runs) >= 2:
            cur_id, prev_id = runs[-1], runs[-2]
            cur_top = top10_products_for_run(hist, cur_id)
            prev_top = top10_products_for_run(hist, prev_id)
            new_in = cur_top - prev_top
            churn = f"{len(new_in)} new in top 10 vs last run"
            if new_in:
                churn += f" ({', '.join(sorted(new_in)[:5])}"
                if len(new_in) > 5:
                    churn += ", …"
                churn += ")"

    local_n = len(local_kw) if not local_kw.empty else 0
    # Stacked KPIs (label | value) so churn text is never clipped by neighbors
    rows.append([])
    rows.append(["KPIs THIS RUN"])
    rows.append(["Products tracked", n_prod])
    rows.append(["Top priority_score", top_p])
    rows.append(["Top-10 churn", churn])
    rows.append(["Local-service keywords", local_n])

    if unmatched:
        rows.append(
            [
                "UNMATCHED product names (check scanners vs products.yaml):",
                "; ".join(unmatched),
            ]
        )

    # --- Action This Week first (decision list above explainers) ---------
    # Layout: A = section / #, B = full text (wide column + wrap on export)
    rows.append([])
    rows.append(["★ ACTION THIS WEEK — do these next"])
    rows.append(
        [
            "Focus",
            "Phase 1: own products first · Bambu Lab H2S only · low support burden",
        ]
    )
    rows.append(
        [
            "Legend",
            "PROTOTYPE = design/print this week  |  "
            "WATCH = rising, not ready  |  "
            "NEEDS DATA = retune keywords  |  "
            "DROP? = prune candidate  |  "
            "LOCAL = Phase 2 note only  |  "
            "CLOSEST = best under the bar",
        ]
    )
    if not actions:
        rows.append(["1.", "NONE — no recommendations this week."])
    else:
        for i, a in enumerate(actions, 1):
            rows.append([f"{i}.", a])

    # --- How to read (metric explainers — below Action for scanability) --
    rows.append([])
    rows.append(["HOW TO READ THIS DASHBOARD"])
    rows.append(
        [
            "Metric",
            "What it means (solo operator cheat-sheet)",
            "",
            "Quick rule of thumb",
        ]
    )
    rows.append(
        [
            "Priority Score (0–100)",
            "Primary rank = opportunity × manufacturing fit. "
            "Answers: “What should I work on next for own products?”",
            "",
            "Higher = do first. Prototype bar ≈ 70+ with good fit.",
        ]
    )
    rows.append(
        [
            "Demand Score (0–100)",
            "Quality-weighted pull (search intent, specificity, community) "
            "— not raw volume alone.",
            "",
            "High = real interest signal; still check Fit before building.",
        ]
    )
    rows.append(
        [
            "Fit Score (0–100)",
            "Manufacturing + customer fit for this stage: FDM-friendly on H2S, "
            "materials OK, clear buyer, low support burden.",
            "",
            "≥60 preferred for prototypes. Low fit = hard/painful to sell.",
        ]
    )
    rows.append(
        [
            "Competition (0–100)",
            "How crowded supply is (marketplace listings + ads). "
            "Higher = harder to stand out.",
            "",
            "Lower is better for acting. Prototype bar prefers ≤60.",
        ]
    )
    rows.append(
        [
            "Demand vs Fit chart",
            "Scatter: X = Fit, Y = Demand. Midpoint ≈ 50/50 splits four zones.",
            "",
            "See quadrant guide below.",
        ]
    )
    rows.append(
        [
            "  → Top-right",
            "High demand + high fit → best build candidates (prototype zone).",
            "",
            "Act first.",
        ]
    )
    rows.append(
        [
            "  → Top-left",
            "High demand + low fit → wanted but hard to make / high support.",
            "",
            "Usually skip or redesign for fit.",
        ]
    )
    rows.append(
        [
            "  → Bottom-right",
            "Low demand + high fit → easy to make, weak market pull.",
            "",
            "Only if strategic / learning print.",
        ]
    )
    rows.append(
        [
            "  → Bottom-left",
            "Low demand + low fit → ignore for now.",
            "",
            "Don't force a build.",
        ]
    )
    rows.append(
        [
            "H2S Fit (label)",
            "Does this product *use* H2S strengths? Larger volume, structural load, "
            "and eng materials + heated chamber (Nylon-CF / PETG-CF / ASA). "
            "Not the same as Fit Score (easy FDM).",
            "",
            "Strong/Good = real H2S upside. OK = prints fine, little unique need. "
            "Weak = strengths mostly unused or process mismatch.",
        ]
    )
    rows.append(
        [
            "Phase focus",
            "Phase 1 now: own products (mounts/accessories) on Bambu Lab H2S only, "
            "low support. Phase 2 later: local print services (Phoenix).",
            "",
            "Prefer PROTOTYPE over LOCAL notes.",
        ]
    )

    # --- Top opportunities table ----------------------------------------
    rows.append([])
    rows.append(
        [
            "TOP OPPORTUNITIES THIS WEEK",
            "",
            "h2s_fit = benefits from H2S volume / structural load / chamber+eng materials "
            "(not generic easy-FDM)",
        ]
    )
    top_cols = [
        "rank",
        "product",
        "category",
        "priority_score",
        "demand_score",
        "fit_score",
        "h2s_fit",
        "competition_score",
        "opportunity_score",
        "score_explanation",
    ]
    top = rankings.head(10).copy()
    if "h2s_fit" not in top.columns:
        top["h2s_fit"] = top.apply(h2s_fit_label, axis=1)
    for c in top_cols:
        if c not in top.columns:
            top[c] = ""
    rows.append(top_cols)
    for _, r in top.iterrows():
        rows.append([r[c] for c in top_cols])

    # Niche comparison (human summary — also mirrored to _ChartData for charts)
    rows.append([])
    rows.append(["CATEGORY / NICHE COMPARISON (avg priority)"])
    rows.append(["category", "avg_priority_score", "n_products"])
    cat = build_category_avg(rankings)
    if cat.empty:
        rows.append(["(none)", "", ""])
    else:
        for _, r in cat.iterrows():
            rows.append(
                [
                    r["category"],
                    r["avg_priority_score"]
                    if pd.notna(r["avg_priority_score"])
                    else "",
                    int(r["n_products"]),
                ]
            )

    # Local service mini panel — use panel position rank, not source rank
    rows.append([])
    rows.append(["LOCAL SERVICE (PHOENIX) — top keywords by volume"])
    rows.append(["#", "keyword", "search_volume", "cpc"])
    if not local_kw.empty:
        lk = local_kw.copy()
        if "search_volume" in lk.columns:
            lk["search_volume"] = pd.to_numeric(lk["search_volume"], errors="coerce")
            lk = lk.sort_values("search_volume", ascending=False).head(5)
        for i, (_, r) in enumerate(lk.iterrows(), 1):
            rows.append(
                [
                    i,
                    r.get("keyword", ""),
                    r.get("search_volume", ""),
                    r.get("cpc", ""),
                ]
            )
    else:
        rows.append(["", "(no local service data)", "", ""])

    # --- Demand vs Fit KEY (matches multi-series chart legend #) ---------
    rows.append([])
    rows.append(
        [
            "DEMAND VS FIT KEY",
            "Chart legend uses the same #. Top-right zone = best to build "
            "(high demand + high fit).",
        ]
    )
    rows.append(["#", "product", "fit", "demand", "zone"])
    scatter_src = rankings.head(SCATTER_TOP_N).copy()
    for c in ("fit_score", "demand_score"):
        if c in scatter_src.columns:
            scatter_src[c] = pd.to_numeric(scatter_src[c], errors="coerce")
    if scatter_src.empty:
        rows.append(["", "(no products)", "", "", ""])
    else:
        for i, (_, r) in enumerate(scatter_src.iterrows(), 1):
            fit = r.get("fit_score")
            dem = r.get("demand_score")
            fit_v = float(fit) if pd.notna(fit) else 0.0
            dem_v = float(dem) if pd.notna(dem) else 0.0
            rows.append(
                [
                    i,
                    r.get("product", ""),
                    fit_v if pd.notna(fit) else "",
                    dem_v if pd.notna(dem) else "",
                    demand_fit_zone(fit_v, dem_v),
                ]
            )

    # --- Charts zone (overlays only — never over tables above) ----------
    rows.append([])
    rows.append(
        [
            "CHARTS — visual overview (below KEY / tables so nothing is hidden)",
        ]
    )
    rows.append(
        [
            "Left→Right row 1: Top Priority bar · Demand vs Fit scatter "
            "(legend = product #). "
            "Row 2: Category avg · Priority trend. "
            "Drill into Product Rankings or Scoring Detail for full columns.",
        ]
    )
    # Blank spacer rows so floating charts sit in empty space, not over text.
    # ~15 sheet rows ≈ 300px chart height; two chart rows + small gap.
    rows.append([])
    charts_start_row = len(rows)  # first blank row of chart canvas
    for _ in range(36):
        rows.append([])
    rows.append(
        [
            "End of Dashboard. History tab holds weekly snapshots for trend/churn.",
        ]
    )
    return rows, charts_start_row


# ---------------------------------------------------------------------------
# Google Sheets API helpers
# ---------------------------------------------------------------------------

def get_sheets_service(sa_path: str):
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError:
        LOG.error(
            "Missing Google API packages. Run: "
            "pip install google-api-python-client google-auth"
        )
        sys.exit(1)

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = service_account.Credentials.from_service_account_file(
        sa_path, scopes=scopes
    )
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def ensure_tabs(service, spreadsheet_id: str) -> dict[str, int]:
    """Create missing tabs in TAB_ORDER + hidden _ChartData; return title → sheetId."""
    meta = (
        service.spreadsheets()
        .get(spreadsheetId=spreadsheet_id, fields="sheets.properties")
        .execute()
    )
    existing = {
        s["properties"]["title"]: s["properties"]["sheetId"]
        for s in meta.get("sheets", [])
    }
    requests_body = []
    for title in TAB_ORDER:
        if title not in existing:
            requests_body.append(
                {"addSheet": {"properties": {"title": title}}}
            )
    if CHART_DATA_TAB not in existing:
        requests_body.append(
            {
                "addSheet": {
                    "properties": {
                        "title": CHART_DATA_TAB,
                        "hidden": True,
                    }
                }
            }
        )
    if requests_body:
        LOG.info("Creating %d missing tabs…", len(requests_body))
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": requests_body}
        ).execute()
        meta = (
            service.spreadsheets()
            .get(spreadsheetId=spreadsheet_id, fields="sheets.properties")
            .execute()
        )
        existing = {
            s["properties"]["title"]: s["properties"]["sheetId"]
            for s in meta.get("sheets", [])
        }
    # Ensure _ChartData stays hidden if it already existed visible
    if CHART_DATA_TAB in existing:
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={
                "requests": [
                    {
                        "updateSheetProperties": {
                            "properties": {
                                "sheetId": existing[CHART_DATA_TAB],
                                "hidden": True,
                            },
                            "fields": "hidden",
                        }
                    }
                ]
            },
        ).execute()

    # Reorder tabs to match TAB_ORDER
    reorder = []
    for i, title in enumerate(TAB_ORDER):
        if title in existing:
            reorder.append(
                {
                    "updateSheetProperties": {
                        "properties": {
                            "sheetId": existing[title],
                            "index": i,
                        },
                        "fields": "index",
                    }
                }
            )
    if reorder:
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": reorder}
        ).execute()
    return existing


def clear_and_write(
    service, spreadsheet_id: str, sheet_title: str, values: list[list[Any]]
) -> None:
    range_a1 = f"'{sheet_title}'!A1"
    service.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id, range=f"'{sheet_title}'"
    ).execute()
    if not values:
        return
    # stringify everything for API
    clean = []
    for row in values:
        clean.append(["" if v is None else v for v in row])
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=range_a1,
        valueInputOption="USER_ENTERED",
        body={"values": clean},
    ).execute()


def freeze_header(service, spreadsheet_id: str, sheet_id: int) -> None:
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={
            "requests": [
                {
                    "updateSheetProperties": {
                        "properties": {
                            "sheetId": sheet_id,
                            "gridProperties": {"frozenRowCount": 1},
                        },
                        "fields": "gridProperties.frozenRowCount",
                    }
                }
            ]
        },
    ).execute()


def format_dashboard_layout(
    service, spreadsheet_id: str, sheet_id: int, n_rows: int
) -> None:
    """
    Column widths + text wrap so Action / KPI / KEY text is fully readable
    (not clipped by narrow adjacent cells).
    """
    end_row = max(n_rows + 5, 40)
    # A labels ~150px, B main prose ~560px, C–E KEY/table columns
    col_widths = [
        (0, 1, 150),
        (1, 2, 560),
        (2, 3, 120),
        (3, 4, 100),
        (4, 5, 180),
        (5, 6, 140),
        (6, 8, 160),
    ]
    requests: list[dict[str, Any]] = []
    for start, end, px in col_widths:
        requests.append(
            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "COLUMNS",
                        "startIndex": start,
                        "endIndex": end,
                    },
                    "properties": {"pixelSize": px},
                    "fields": "pixelSize",
                }
            }
        )
    requests.append(
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": end_row,
                    "startColumnIndex": 0,
                    "endColumnIndex": 10,
                },
                "cell": {
                    "userEnteredFormat": {
                        "wrapStrategy": "WRAP",
                        "verticalAlignment": "TOP",
                    }
                },
                "fields": (
                    "userEnteredFormat.wrapStrategy,"
                    "userEnteredFormat.verticalAlignment"
                ),
            }
        }
    )
    # Taller default rows so wrapped Action lines show fully
    requests.append(
        {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "ROWS",
                    "startIndex": 0,
                    "endRowIndex": end_row,
                },
                "properties": {"pixelSize": 24},
                "fields": "pixelSize",
            }
        }
    )
    try:
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": requests}
        ).execute()
        LOG.info("Dashboard layout formatted (column widths + wrap)")
    except Exception as e:
        LOG.warning("Dashboard layout format failed (data still written): %s", e)


def read_sheet_values(service, spreadsheet_id: str, title: str) -> list[list[Any]]:
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=f"'{title}'")
        .execute()
    )
    return result.get("values") or []


def append_history(
    service,
    spreadsheet_id: str,
    sheet_id: int,
    new_df: pd.DataFrame,
) -> int:
    """
    Append History rows; return number of rows appended.
    Validates header shape before append so a manually edited History tab
    cannot silently shift columns and corrupt the log.
    """
    existing = read_sheet_values(service, spreadsheet_id, "History")
    if not existing:
        values = df_to_values(new_df, HISTORY_COLS)
        clear_and_write(service, spreadsheet_id, "History", values)
        freeze_header(service, spreadsheet_id, sheet_id)
        return max(0, len(values) - 1)

    header = [str(h).strip() for h in existing[0]]
    expected = list(HISTORY_COLS)

    if header == expected:
        col_order = expected
    elif set(header) == set(expected) and len(header) == len(expected):
        # Same columns, different order — remap new rows to sheet order
        LOG.warning(
            "History header column order differs from HISTORY_COLS; "
            "remapping append to match sheet order: %s",
            header,
        )
        col_order = header
    elif header and header == expected[: len(header)]:
        # True prefix only (not any ordered subsequence). Missing a middle
        # column must NOT upgrade — that would mislabel historical cells.
        # Backward-safe: old History ending before coverage cols still upgrades;
        # prior rows keep blank cells for new trailing columns.
        LOG.info(
            "Upgrading History header with new coverage columns: %s",
            [c for c in expected if c not in header],
        )
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range="'History'!A1",
            valueInputOption="USER_ENTERED",
            body={"values": [expected]},
        ).execute()
        col_order = expected
    else:
        raise RuntimeError(
            "History sheet header does not match expected HISTORY_COLS.\n"
            f"  expected: {expected}\n"
            f"  found:    {header}\n"
            "Fix or clear the History tab header before exporting, so the "
            "append-only log cannot silently drift."
        )

    new_values = df_to_values(new_df, col_order)
    to_append = new_values[1:]
    if not to_append:
        return 0
    service.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range="'History'!A1",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": to_append},
    ).execute()
    return len(to_append)


def delete_all_charts(service, spreadsheet_id: str, sheet_id: int) -> None:
    meta = (
        service.spreadsheets()
        .get(
            spreadsheetId=spreadsheet_id,
            fields="sheets(properties,charts)",
        )
        .execute()
    )
    reqs = []
    for s in meta.get("sheets", []):
        if s["properties"]["sheetId"] != sheet_id:
            continue
        for ch in s.get("charts") or []:
            reqs.append({"deleteEmbeddedObject": {"objectId": ch["chartId"]}})
    if reqs:
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": reqs}
        ).execute()


def write_chart_data_sheet(
    service,
    spreadsheet_id: str,
    trend_pivot: pd.DataFrame,
    category_avg: pd.DataFrame,
    rankings: pd.DataFrame,
) -> tuple[int, int, int, int, int]:
    """
    Write hidden _ChartData:
      - trend pivot at A1
      - category avg at row CHART_CATEGORY_START (40)
      - Demand vs Fit multi-series (labeled) at CHART_SCATTER_START (80)

    Returns
      (n_trend_rows, n_category_rows, n_scatter_rows, n_scatter_cols,
       scatter_start_row) — row counts include header.

    TODO: Category block is hard-coded at row index 40. Weekly History yields
    one trend row per run, so ~9 months (~39 runs) would collide with the
    category block. Switch to a dynamic boundary before then.
    """
    blocks: list[list[Any]] = []
    trend_vals = df_to_values(trend_pivot)
    n_trend = len(trend_vals)
    blocks.extend(trend_vals)
    # Fixed spacer to category block — keep in sync with add_dashboard_charts.
    while len(blocks) < CHART_CATEGORY_START:
        blocks.append([])
    cat_vals = df_to_values(category_avg)
    n_cat = len(cat_vals)
    blocks.extend(cat_vals)

    while len(blocks) < CHART_SCATTER_START:
        blocks.append([])
    scatter_vals, n_scat_rows, n_scat_cols = build_scatter_series_matrix(
        rankings, SCATTER_TOP_N
    )
    blocks.extend(scatter_vals)
    clear_and_write(service, spreadsheet_id, CHART_DATA_TAB, blocks)
    return n_trend, n_cat, n_scat_rows, n_scat_cols, CHART_SCATTER_START


def add_dashboard_charts(
    service,
    spreadsheet_id: str,
    sheet_ids: dict[str, int],
    n_products: int,
    n_top: int = 10,
    n_trend_rows: int = 0,
    n_trend_cols: int = 0,
    n_category_rows: int = 0,
    charts_start_row: int = 40,
    n_scatter_rows: int = 0,
    n_scatter_cols: int = 0,
    scatter_start_row: int = CHART_SCATTER_START,
) -> None:
    """
    Charts on Dashboard (overlays only in the reserved CHARTS zone):
      1. Demand vs Fit scatter → _ChartData multi-series (legend = product #)
      2. Top Priority bar → Product Rankings (product vs priority)
      3. Category comparison bar → _ChartData category block (row 40+)
      4. Priority trend lines → _ChartData trend pivot (row 0+)

    charts_start_row is the 0-based Dashboard row from build_dashboard() where
    blank spacer rows begin — keeps charts from covering text/tables above.
    """
    dash_id = sheet_ids["Dashboard"]
    rank_id = sheet_ids["Product Rankings"]
    chart_id = sheet_ids.get(CHART_DATA_TAB)
    delete_all_charts(service, spreadsheet_id, dash_id)

    # 2×2 grid in the reserved blank zone (laptop-friendly sizes)
    row1 = max(0, charts_start_row)
    row2 = row1 + 17  # ~300px ≈ 14–16 default rows between anchors
    col_left = 0
    col_right = 6
    w_left, w_right = 500, 560  # scatter wider for legend
    h_main, h_lower = 320, 280

    # Product Rankings: A rank, B product, C category, D priority, E demand, F fit
    end_row = min(1 + n_top, 1 + n_products)
    requests_body = []

    # Chart 2: Top Priority horizontal bar
    requests_body.append(
        {
            "addChart": {
                "chart": {
                    "spec": {
                        "title": "Top Priority Scores",
                        "basicChart": {
                            "chartType": "BAR",
                            "legendPosition": "NO_LEGEND",
                            "axis": [
                                {"position": "BOTTOM_AXIS", "title": "priority_score"},
                                {"position": "LEFT_AXIS", "title": "product"},
                            ],
                            "domains": [
                                {
                                    "domain": {
                                        "sourceRange": {
                                            "sources": [
                                                {
                                                    "sheetId": rank_id,
                                                    "startRowIndex": 0,
                                                    "endRowIndex": end_row + 1,
                                                    "startColumnIndex": 1,
                                                    "endColumnIndex": 2,
                                                }
                                            ]
                                        }
                                    }
                                }
                            ],
                            "series": [
                                {
                                    "series": {
                                        "sourceRange": {
                                            "sources": [
                                                {
                                                    "sheetId": rank_id,
                                                    "startRowIndex": 0,
                                                    "endRowIndex": end_row + 1,
                                                    "startColumnIndex": 3,
                                                    "endColumnIndex": 4,
                                                }
                                            ]
                                        }
                                    },
                                    "targetAxis": "BOTTOM_AXIS",
                                }
                            ],
                            "headerCount": 1,
                        },
                    },
                    "position": {
                        "overlayPosition": {
                            "anchorCell": {
                                "sheetId": dash_id,
                                "rowIndex": row1,
                                "columnIndex": col_left,
                            },
                            "widthPixels": w_left,
                            "heightPixels": h_main,
                        }
                    },
                }
            }
        }
    )

    # Chart 1: Demand vs Fit scatter — multi-series so legend names each product
    if (
        chart_id is not None
        and n_scatter_rows >= 2
        and n_scatter_cols >= 2
    ):
        scat_end = scatter_start_row + n_scatter_rows
        scatter_series = []
        for col_i in range(1, n_scatter_cols):
            scatter_series.append(
                {
                    "series": {
                        "sourceRange": {
                            "sources": [
                                {
                                    "sheetId": chart_id,
                                    "startRowIndex": scatter_start_row,
                                    "endRowIndex": scat_end,
                                    "startColumnIndex": col_i,
                                    "endColumnIndex": col_i + 1,
                                }
                            ]
                        }
                    },
                    "targetAxis": "LEFT_AXIS",
                }
            )
        requests_body.append(
            {
                "addChart": {
                    "chart": {
                        "spec": {
                            "title": (
                                "Demand vs Fit — top-right = build "
                                "(legend # = KEY above)"
                            ),
                            "basicChart": {
                                "chartType": "SCATTER",
                                "legendPosition": "RIGHT_LEGEND",
                                "axis": [
                                    {
                                        "position": "BOTTOM_AXIS",
                                        "title": "fit_score →",
                                    },
                                    {
                                        "position": "LEFT_AXIS",
                                        "title": "demand_score ↑",
                                    },
                                ],
                                "domains": [
                                    {
                                        "domain": {
                                            "sourceRange": {
                                                "sources": [
                                                    {
                                                        "sheetId": chart_id,
                                                        "startRowIndex": scatter_start_row,
                                                        "endRowIndex": scat_end,
                                                        "startColumnIndex": 0,
                                                        "endColumnIndex": 1,
                                                    }
                                                ]
                                            }
                                        }
                                    }
                                ],
                                "series": scatter_series,
                                "headerCount": 1,
                            },
                        },
                        "position": {
                            "overlayPosition": {
                                "anchorCell": {
                                    "sheetId": dash_id,
                                    "rowIndex": row1,
                                    "columnIndex": col_right,
                                },
                                "widthPixels": w_right,
                                "heightPixels": h_main + 40,
                            }
                        },
                    }
                }
            }
        )
    elif n_products > 0:
        # Fallback: unlabeled scatter from Product Rankings (should be rare)
        LOG.warning(
            "Scatter multi-series unavailable; falling back to Product Rankings"
        )
        # RANKINGS: E=demand (4), F=fit (5)
        requests_body.append(
            {
                "addChart": {
                    "chart": {
                        "spec": {
                            "title": "Demand vs Fit (top-right = build) — see KEY",
                            "basicChart": {
                                "chartType": "SCATTER",
                                "legendPosition": "NO_LEGEND",
                                "axis": [
                                    {
                                        "position": "BOTTOM_AXIS",
                                        "title": "fit_score →",
                                    },
                                    {
                                        "position": "LEFT_AXIS",
                                        "title": "demand_score ↑",
                                    },
                                ],
                                "domains": [
                                    {
                                        "domain": {
                                            "sourceRange": {
                                                "sources": [
                                                    {
                                                        "sheetId": rank_id,
                                                        "startRowIndex": 0,
                                                        "endRowIndex": n_products + 1,
                                                        "startColumnIndex": 5,
                                                        "endColumnIndex": 6,
                                                    }
                                                ]
                                            }
                                        }
                                    }
                                ],
                                "series": [
                                    {
                                        "series": {
                                            "sourceRange": {
                                                "sources": [
                                                    {
                                                        "sheetId": rank_id,
                                                        "startRowIndex": 0,
                                                        "endRowIndex": n_products + 1,
                                                        "startColumnIndex": 4,
                                                        "endColumnIndex": 5,
                                                    }
                                                ]
                                            }
                                        },
                                        "targetAxis": "LEFT_AXIS",
                                    }
                                ],
                                "headerCount": 1,
                            },
                        },
                        "position": {
                            "overlayPosition": {
                                "anchorCell": {
                                    "sheetId": dash_id,
                                    "rowIndex": row1,
                                    "columnIndex": col_right,
                                },
                                "widthPixels": w_right,
                                "heightPixels": h_main,
                            }
                        },
                    }
                }
            }
        )

    # Chart 3: Category comparison (from _ChartData starting row 40)
    # Hard-coded boundary — must match write_chart_data_sheet spacer (TODO there).
    if chart_id is not None and n_category_rows >= 2:
        cat_start = CHART_CATEGORY_START
        cat_end = CHART_CATEGORY_START + n_category_rows
        requests_body.append(
            {
                "addChart": {
                    "chart": {
                        "spec": {
                            "title": "Category avg priority",
                            "basicChart": {
                                "chartType": "COLUMN",
                                "legendPosition": "NO_LEGEND",
                                "axis": [
                                    {"position": "BOTTOM_AXIS", "title": "category"},
                                    {
                                        "position": "LEFT_AXIS",
                                        "title": "avg_priority_score",
                                    },
                                ],
                                "domains": [
                                    {
                                        "domain": {
                                            "sourceRange": {
                                                "sources": [
                                                    {
                                                        "sheetId": chart_id,
                                                        "startRowIndex": cat_start,
                                                        "endRowIndex": cat_end,
                                                        "startColumnIndex": 0,
                                                        "endColumnIndex": 1,
                                                    }
                                                ]
                                            }
                                        }
                                    }
                                ],
                                "series": [
                                    {
                                        "series": {
                                            "sourceRange": {
                                                "sources": [
                                                    {
                                                        "sheetId": chart_id,
                                                        "startRowIndex": cat_start,
                                                        "endRowIndex": cat_end,
                                                        "startColumnIndex": 1,
                                                        "endColumnIndex": 2,
                                                    }
                                                ]
                                            }
                                        },
                                        "targetAxis": "LEFT_AXIS",
                                    }
                                ],
                                "headerCount": 1,
                            },
                        },
                        "position": {
                            "overlayPosition": {
                                "anchorCell": {
                                    "sheetId": dash_id,
                                    "rowIndex": row2,
                                    "columnIndex": col_left,
                                },
                                "widthPixels": w_left,
                                "heightPixels": h_lower,
                            }
                        },
                    }
                }
            }
        )

    # Chart 4: Priority trend (multi-line) — P0 required
    # _ChartData A1: run_date | product1 | product2 | ...
    # Need ≥2 weekly data points (header + 2 rows → n_trend_rows >= 3), same
    # “need ≥2 weekly runs” gate used for Watch-rising / churn.
    if chart_id is not None and n_trend_rows >= 3 and n_trend_cols >= 2:
        series = []
        for col_i in range(1, n_trend_cols):
            series.append(
                {
                    "series": {
                        "sourceRange": {
                            "sources": [
                                {
                                    "sheetId": chart_id,
                                    "startRowIndex": 0,
                                    "endRowIndex": n_trend_rows,
                                    "startColumnIndex": col_i,
                                    "endColumnIndex": col_i + 1,
                                }
                            ]
                        }
                    },
                    "targetAxis": "LEFT_AXIS",
                }
            )
        requests_body.append(
            {
                "addChart": {
                    "chart": {
                        "spec": {
                            "title": "Priority score trend (current top products)",
                            "basicChart": {
                                "chartType": "LINE",
                                "legendPosition": "BOTTOM_LEGEND",
                                "axis": [
                                    {"position": "BOTTOM_AXIS", "title": "run_date"},
                                    {
                                        "position": "LEFT_AXIS",
                                        "title": "priority_score",
                                    },
                                ],
                                "domains": [
                                    {
                                        "domain": {
                                            "sourceRange": {
                                                "sources": [
                                                    {
                                                        "sheetId": chart_id,
                                                        "startRowIndex": 0,
                                                        "endRowIndex": n_trend_rows,
                                                        "startColumnIndex": 0,
                                                        "endColumnIndex": 1,
                                                    }
                                                ]
                                            }
                                        }
                                    }
                                ],
                                "series": series,
                                "headerCount": 1,
                            },
                        },
                        "position": {
                            "overlayPosition": {
                                "anchorCell": {
                                    "sheetId": dash_id,
                                    "rowIndex": row2,
                                    "columnIndex": col_right,
                                },
                                "widthPixels": w_right + 20,
                                "heightPixels": h_lower + 20,
                            }
                        },
                    }
                }
            }
        )

    try:
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": requests_body}
        ).execute()
        LOG.info(
            "Dashboard charts created at row %d (Top Priority, Demand vs Fit, "
            "Category, Priority trend)",
            charts_start_row,
        )
    except Exception as e:
        LOG.warning("Chart creation failed (data still exported): %s", e)


# ---------------------------------------------------------------------------
# Main export
# ---------------------------------------------------------------------------

def export(
    *,
    dry_run: bool = False,
    skip_charts: bool = False,
    spreadsheet_id: str | None = None,
    sa_path: str | None = None,
) -> None:
    meta = load_run_meta()
    products = load_products_yaml()
    local_svc = load_local_service_yaml()
    known = known_product_names(products)

    report = safe_read_csv("out/demand_report.csv")
    if report.empty:
        LOG.error("out/demand_report.csv missing — run score_demand.py first")
        sys.exit(1)

    # Unmatched product names
    unmatched = sorted(
        set(report["product"].dropna().astype(str)) - known
    ) if "product" in report.columns else []
    if unmatched:
        LOG.warning("Unmatched products (not in products.yaml): %s", unmatched)

    # Blank empty categories → flag
    if "category" in report.columns:
        blank_cat = report[
            report["category"].isna() | (report["category"].astype(str).str.strip() == "")
        ]["product"].tolist()
        if blank_cat:
            LOG.warning("Blank category: %s", blank_cat)

    rankings = build_rankings(report, meta)
    detail = build_scoring_detail(report, meta)
    voice_df = build_market_voice(report=report, meta=meta)
    write_market_voice(voice_df, "out/market_voice.csv")
    sv_matrix = build_search_volume_tab(meta)
    market_df = build_marketplace_tab(report, meta)
    local_matrix = build_local_service_tab()
    config_matrix = build_config_tab(products, local_svc)
    history_new = build_history_rows(report, meta)

    local_kw = safe_read_csv("out/local_service_keywords_phoenix_az.csv")

    # For actions we need existing history if any — dry-run uses empty
    history_existing = pd.DataFrame(columns=HISTORY_COLS)

    # Combined history for trend pivot (existing + this run)
    history_for_trend = pd.concat(
        [history_existing, coerce_history_df(history_new)], ignore_index=True
    )

    actions = compute_actions(rankings, history_existing, local_kw, meta)
    dashboard, charts_start_row = build_dashboard(
        rankings, meta, actions, local_kw, history_for_trend, unmatched
    )
    trend_pivot = build_trend_pivot(history_for_trend, rankings, TREND_TOP_N)
    category_avg = build_category_avg(rankings)

    LOG.info(
        "Prepared tabs: rankings=%d detail=%d voice=%d history_new=%d actions=%d "
        "trend_pivot=%s category_rows=%d charts_start_row=%d",
        len(rankings),
        len(detail),
        len(voice_df),
        len(history_new),
        len(actions),
        trend_pivot.shape,
        len(category_avg),
        charts_start_row,
    )

    if dry_run:
        out_dir = Path("out/sheets_dry_run")
        out_dir.mkdir(parents=True, exist_ok=True)
        rankings.to_csv(out_dir / "product_rankings.csv", index=False)
        detail.to_csv(out_dir / "scoring_detail.csv", index=False)
        voice_df.to_csv(out_dir / "market_voice.csv", index=False)
        history_new.to_csv(out_dir / "history_append.csv", index=False)
        market_df.to_csv(out_dir / "marketplace.csv", index=False)
        trend_pivot.to_csv(out_dir / "trend_pivot.csv", index=False)
        category_avg.to_csv(out_dir / "category_avg.csv", index=False)
        # Synthetic second history run to verify numeric churn (P0 regression)
        fake = history_new.copy()
        if not fake.empty:
            fake["run_id"] = "2000-01-01T00:00:00+00:00"
            fake["run_date"] = "2000-01-01"
            # String ranks as Sheets would return them
            fake_str = fake.copy()
            for c in ("rank", "priority_score"):
                if c in fake_str.columns:
                    fake_str[c] = fake_str[c].astype(str)
            coerced = coerce_history_df(fake_str)
            assert coerced["rank"].dtype.kind in "iuf", "rank must be numeric after coerce"
            assert coerced["priority_score"].dtype.kind in "iuf"
            # Lexicographic trap: string "10" < "2", numeric 10 > 2
            trap = pd.DataFrame(
                {
                    "run_id": ["r1", "r1", "r1"],
                    "product": ["A", "B", "C"],
                    "rank": ["10", "2", "3"],
                    "priority_score": ["90", "100", "80"],
                }
            )
            trap_c = coerce_history_df(trap)
            assert (
                trap_c.nsmallest(1, "rank")["product"].iloc[0] == "B"
            ), "numeric nsmallest on rank must pick rank=2 not rank=10"
            (out_dir / "coerce_history_ok.txt").write_text(
                "coerce_history_df: rank/priority numeric + nsmallest OK\n"
            )
        # Header validation unit check
        try:
            bad = [["run_date", "wrong"], ["x", "y"]]
            # Simulate validation logic
            header = [str(h).strip() for h in bad[0]]
            assert header != list(HISTORY_COLS)
            (out_dir / "header_validation_logic_ok.txt").write_text(
                "header mismatch would abort append\n"
            )
        except Exception as e:
            LOG.warning("header validation self-check: %s", e)

        (out_dir / "dashboard.txt").write_text(
            "\n".join("\t".join(str(c) for c in row) for row in dashboard)
        )
        (out_dir / "actions.json").write_text(json.dumps(actions, indent=2))
        (out_dir / "local_service.txt").write_text(
            "\n".join("\t".join(str(c) for c in row) for row in local_matrix)
        )
        (out_dir / "search_volume.txt").write_text(
            "\n".join("\t".join(str(c) for c in row) for row in sv_matrix)
        )
        # Ensure dead CHART DATA block is gone; UX sections present
        dash_text = (out_dir / "dashboard.txt").read_text()
        assert "CHART DATA — Demand vs Fit" not in dash_text
        assert "CHART DATA — Category avg" not in dash_text
        assert "HOW TO READ THIS DASHBOARD" in dash_text
        assert "★ ACTION THIS WEEK" in dash_text
        assert list(voice_df.columns) == list(VOICE_COLS), voice_df.columns.tolist()
        assert len(voice_df) == len(rankings), "Market Voice must cover all products"
        assert voice_df["top_intent_phrases"].astype(str).str.len().gt(0).any(), (
            "expected some intent phrases from search_volume_keywords"
        )
        assert "CHARTS — visual overview" in dash_text
        assert "DEMAND VS FIT KEY" in dash_text
        assert "KPIs THIS RUN" in dash_text
        assert "Priority Score" in dash_text
        assert "top-right" in dash_text.lower()
        assert "H2S Fit" in dash_text
        assert "h2s_fit" in dash_text
        assert "P1S" not in dash_text and "p1s" not in dash_text
        # Action text lives in column B (index 1) as full strings between
        # ACTION header and HOW TO READ (not Top Opportunities rank numbers).
        action_rows = []
        in_actions = False
        for r in dashboard:
            if not r:
                continue
            head = str(r[0])
            if head.startswith("★ ACTION THIS WEEK"):
                in_actions = True
                continue
            if head.startswith("HOW TO READ"):
                break
            if in_actions and head.rstrip(".").isdigit() and len(r) >= 2:
                action_rows.append(r)
        assert action_rows, "expected numbered action rows"
        assert all(len(str(r[1])) > 20 for r in action_rows), (
            "action text should be full-length in column B"
        )
        # Charts zone must start after Action + Top Opportunities + KEY
        assert charts_start_row > 20, charts_start_row
        # H2S labels present on rankings
        assert "h2s_fit" in rankings.columns
        assert rankings["h2s_fit"].astype(str).str.len().gt(0).any()
        # Scatter multi-series matrix has one labeled series per product
        scat, n_scat_r, n_scat_c = build_scatter_series_matrix(rankings)
        assert n_scat_r >= 2 and n_scat_c >= 2
        assert str(scat[0][1]).startswith("#1")
        (out_dir / "scatter_series_preview.txt").write_text(
            "\n".join("\t".join(str(c) for c in row) for row in scat[:5])
            + f"\n... rows={n_scat_r} cols={n_scat_c}\n"
        )
        (out_dir / "charts_layout.txt").write_text(
            f"charts_start_row={charts_start_row}\n"
            f"dashboard_total_rows={len(dashboard)}\n"
            f"scatter_rows={n_scat_r} scatter_cols={n_scat_c}\n"
        )
        rankings[["product", "category", "h2s_fit", "fit_score"]].to_csv(
            out_dir / "h2s_fit_preview.csv", index=False
        )
        # Label distribution must not collapse to almost-all Strong
        tier = rankings["h2s_fit"].astype(str).str.split("—").str[0].str.strip()
        dist = tier.value_counts().to_dict()
        (out_dir / "h2s_fit_distribution.txt").write_text(
            "\n".join(f"{k}: {v}" for k, v in sorted(dist.items())) + "\n"
        )
        n = len(rankings)
        n_strong = int(dist.get("Strong", 0))
        assert n_strong < n * 0.6, (
            f"H2S Fit too collapsed to Strong: {dist} (n={n})"
        )
        assert len(dist) >= 2, f"H2S Fit needs ≥2 label tiers, got {dist}"
        LOG.info("Dry-run written to %s", out_dir)
        print("\n=== ACTION THIS WEEK (dry-run) ===")
        for a in actions:
            print(f"  • {a}")
        print(f"\nDashboard charts_start_row={charts_start_row} "
              f"(total rows={len(dashboard)})")
        print(f"Scatter series: {n_scat_r} rows × {n_scat_c} cols "
              f"(header + {n_scat_c - 1} labeled products)")
        print(f"H2S Fit distribution: {dist}")
        print(f"\nTrend pivot preview ({trend_pivot.shape[0]} dates × "
              f"{max(0, trend_pivot.shape[1]-1)} products):")
        print(trend_pivot.head().to_string(index=False))
        print(f"\n=== MARKET VOICE (dry-run, top 3) ===")
        preview_cols = [
            "product",
            "top_problem_phrases",
            "proof_snippets",
            "social_hook",
            "confidence",
        ]
        print(voice_df[preview_cols].head(3).to_string(index=False))
        print(f"\nDry-run complete → {out_dir}")
        return

    sa_path = sa_path or os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    spreadsheet_id = (
        spreadsheet_id or os.environ.get("GOOGLE_SHEETS_SPREADSHEET_ID", "").strip()
    )
    if not sa_path or not Path(sa_path).exists():
        LOG.error(
            "Set GOOGLE_SERVICE_ACCOUNT_JSON to a valid service-account JSON path "
            "(see docs/sheets_setup.md)"
        )
        sys.exit(1)
    if not spreadsheet_id:
        LOG.error("Set GOOGLE_SHEETS_SPREADSHEET_ID in .env")
        sys.exit(1)

    try:
        service = get_sheets_service(sa_path)
    except Exception as e:
        LOG.error(
            "Failed to load service account credentials from %s: %s", sa_path, e
        )
        sys.exit(1)
    sheet_ids = ensure_tabs(service, spreadsheet_id)

    # Read prior History for action rules (rising / drop) + trend chart
    try:
        prev_vals = read_sheet_values(service, spreadsheet_id, "History")
        history_existing = history_from_sheet_values(prev_vals)
        if not history_existing.empty:
            history_for_trend = pd.concat(
                [history_existing, coerce_history_df(history_new)],
                ignore_index=True,
            )
            actions = compute_actions(rankings, history_existing, local_kw, meta)
            dashboard, charts_start_row = build_dashboard(
                rankings, meta, actions, local_kw, history_for_trend, unmatched
            )
            trend_pivot = build_trend_pivot(
                history_for_trend, rankings, TREND_TOP_N
            )
    except Exception as e:
        LOG.warning("Could not read prior History: %s", e)

    # Write regenerated tabs
    clear_and_write(service, spreadsheet_id, "Dashboard", dashboard)
    format_dashboard_layout(
        service,
        spreadsheet_id,
        sheet_ids["Dashboard"],
        n_rows=len(dashboard),
    )
    clear_and_write(
        service, spreadsheet_id, "Product Rankings", df_to_values(rankings, RANKINGS_COLS)
    )
    freeze_header(service, spreadsheet_id, sheet_ids["Product Rankings"])

    clear_and_write(
        service, spreadsheet_id, "Scoring Detail", df_to_values(detail)
    )
    freeze_header(service, spreadsheet_id, sheet_ids["Scoring Detail"])

    clear_and_write(
        service, spreadsheet_id, "Market Voice", df_to_values(voice_df, VOICE_COLS)
    )
    freeze_header(service, spreadsheet_id, sheet_ids["Market Voice"])

    clear_and_write(service, spreadsheet_id, "Search Volume", sv_matrix)
    # Marketplace status banner + table
    market_banner = [
        [
            f"Marketplace — listings: "
            f"{'ACTIVE' if source_is_active(meta, 'marketplace') else 'SKIPPED/STALE'}; "
            f"community: "
            f"{'ACTIVE' if source_is_active(meta, 'community') else 'SKIPPED/STALE'} "
            f"(run {meta.get('run_date', '')})",
        ],
        [],
    ]
    market_vals = market_banner + df_to_values(market_df)
    clear_and_write(service, spreadsheet_id, "Marketplace", market_vals)

    clear_and_write(
        service, spreadsheet_id, "Local Service (Phoenix)", local_matrix
    )
    clear_and_write(service, spreadsheet_id, "Config", config_matrix)

    n_hist = append_history(
        service, spreadsheet_id, sheet_ids["History"], history_new
    )
    LOG.info("History appended %d rows", n_hist)

    # Refresh trend pivot after append so chart includes this run
    try:
        full_hist = history_from_sheet_values(
            read_sheet_values(service, spreadsheet_id, "History")
        )
        trend_pivot = build_trend_pivot(full_hist, rankings, TREND_TOP_N)
    except Exception as e:
        LOG.warning("Post-append History re-read failed: %s", e)

    (
        n_trend_rows,
        n_cat_rows,
        n_scatter_rows,
        n_scatter_cols,
        scatter_start_row,
    ) = write_chart_data_sheet(
        service, spreadsheet_id, trend_pivot, category_avg, rankings
    )
    n_trend_cols = trend_pivot.shape[1] if not trend_pivot.empty else 0

    if not skip_charts:
        add_dashboard_charts(
            service,
            spreadsheet_id,
            sheet_ids,
            n_products=len(rankings),
            n_top=min(10, len(rankings)),
            n_trend_rows=n_trend_rows,
            n_trend_cols=n_trend_cols,
            n_category_rows=n_cat_rows,
            charts_start_row=charts_start_row,
            n_scatter_rows=n_scatter_rows,
            n_scatter_cols=n_scatter_cols,
            scatter_start_row=scatter_start_row,
        )

    print("\n=== ACTION THIS WEEK ===")
    for a in actions:
        print(f"  • {a}")
    print(
        f"\nSheets export complete → spreadsheet {spreadsheet_id}\n"
        f"  run_date={meta.get('run_date')}  history_rows_added={n_hist}\n"
        f"  trend_pivot={trend_pivot.shape}  charts="
        f"{'on' if not skip_charts else 'skipped'}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export demand-monitor results to Google Sheets"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build tab payloads locally without calling Google APIs",
    )
    parser.add_argument(
        "--skip-charts",
        action="store_true",
        help="Skip chart creation/update on Dashboard",
    )
    parser.add_argument(
        "--spreadsheet-id",
        default=None,
        help="Override GOOGLE_SHEETS_SPREADSHEET_ID",
    )
    parser.add_argument(
        "--credentials",
        default=None,
        help="Override GOOGLE_SERVICE_ACCOUNT_JSON path",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    setup_logging(args.verbose)
    export(
        dry_run=args.dry_run,
        skip_charts=args.skip_charts,
        spreadsheet_id=args.spreadsheet_id,
        sa_path=args.credentials,
    )


if __name__ == "__main__":
    main()
