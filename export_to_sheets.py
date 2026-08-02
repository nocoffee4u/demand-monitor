#!/usr/bin/env python3
"""
export_to_sheets.py
-------------------
Push demand-monitor pipeline outputs into a Google Sheet (Service Account).

Tabs (per docs/sheets_dashboard_spec.md):
  Dashboard, Product Rankings, Scoring Detail, Search Volume,
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
    "Search Volume",
    "Marketplace",
    "Local Service (Phoenix)",
    "History",
    "Config",
]

RANKINGS_COLS = [
    "rank",
    "product",
    "category",
    "priority_score",
    "demand_score",
    "fit_score",
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


def blank_unused_sources(df: pd.DataFrame, meta: dict) -> pd.DataFrame:
    """Turn zeros into blank for skipped sources (display-only copy)."""
    out = df.copy()
    unused = set(meta.get("demand_unused") or [])
    sources = meta.get("sources") or {}

    def source_off(key: str) -> bool:
        if key in sources:
            return not sources[key]
        # Map demand_unused keys to source families
        if key == "reddit":
            return "reddit_volume" in unused or "reddit_engagement" in unused
        if key == "x":
            return "x_volume" in unused or "x_engagement" in unused
        if key == "trends":
            return "trends_interest" in unused or "momentum" in unused
        if key == "search_volume":
            return "search_volume" in unused or "volume_quality" in unused
        if key == "community":
            return "community_downloads" in unused
        return False

    for src, cols in SOURCE_COL_MAP.items():
        if not source_off(src):
            continue
        for c in cols:
            if c in out.columns:
                out[c] = ""
    return out


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
# Action This Week (spec §4)
# ---------------------------------------------------------------------------

def compute_actions(
    rankings: pd.DataFrame,
    history: pd.DataFrame,
    local_kw: pd.DataFrame,
    meta: dict,
) -> list[str]:
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

    # 1. Prototype this week
    proto = r[
        (r["priority_score"] >= 70)
        & (r["fit_score"] >= 60)
        & (r["competition_score"] <= 60)
    ].head(3)
    for _, row in proto.iterrows():
        actions.append(
            f"Prototype this week: {row['product']} "
            f"(priority {row['priority_score']:.0f}, fit {row['fit_score']:.0f}, "
            f"comp {row['competition_score']:.0f})"
        )

    # 2. Watch — rising (needs ≥2 history runs)
    if not history.empty and "product" in history.columns:
        hist = history.copy()
        hist["priority_score"] = pd.to_numeric(hist["priority_score"], errors="coerce")
        rising = []
        for product, g in hist.groupby("product"):
            g = g.sort_values(["run_date", "run_id"])
            if len(g) < 2:
                continue
            prev = float(g.iloc[-2]["priority_score"])
            cur = float(g.iloc[-1]["priority_score"])
            if cur > prev and 50 <= cur < 70:
                rising.append((product, prev, cur))
        rising.sort(key=lambda x: x[2] - x[1], reverse=True)
        if not rising and history["product"].nunique() > 0:
            # only one run overall?
            runs = history["run_id"].nunique() if "run_id" in history.columns else 0
            if runs < 2:
                actions.append(
                    "Watch — rising: insufficient history (need ≥2 weekly runs)"
                )
        for product, prev, cur in rising[:3]:
            actions.append(
                f"Watch — rising: {product} "
                f"(priority {prev:.0f} → {cur:.0f})"
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
                f"Needs more data (keyword tuning, not 'no demand'): {row['product']}"
            )

    # 4. Reconsider / drop — priority < 30 for 3 consecutive history runs
    if not history.empty and "product" in history.columns:
        hist = history.copy()
        hist["priority_score"] = pd.to_numeric(hist["priority_score"], errors="coerce")
        drops = []
        for product, g in hist.groupby("product"):
            g = g.sort_values(["run_date", "run_id"])
            tail = g.tail(3)
            if len(tail) >= 3 and (tail["priority_score"] < 30).all():
                drops.append(product)
        for product in drops[:2]:
            actions.append(
                f"Reconsider / drop: {product} "
                f"(priority < 30 for 3 consecutive runs — prune from products.yaml?)"
            )

    # 5. Local service note
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
                f"Local service (Phase 2 note): “{top.get('keyword')}” "
                f"~{int(top['search_volume'])}/mo in Phoenix — keep on radar"
            )

    if not actions:
        actions.append("Nothing crossed the bar this week — no forced recommendations.")
    return actions[:5]


# ---------------------------------------------------------------------------
# Build tab dataframes / matrices
# ---------------------------------------------------------------------------

def build_rankings(report: pd.DataFrame, meta: dict) -> pd.DataFrame:
    df = blank_unused_sources(report, meta)
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


def build_search_volume_tab() -> list[list[Any]]:
    rows: list[list[Any]] = []
    rows.append(["SECTION A — Per-product search volume summary"])
    sig = safe_read_csv("out/search_volume_signal.csv")
    if sig.empty:
        rows.append(["(no search_volume_signal.csv)"])
    else:
        rows.extend(df_to_values(sig))
    rows.append([])
    rows.append(
        [
            "SECTION B — All queried keywords (flat audit; NOT linked to product)"
        ]
    )
    kws = safe_read_csv("out/search_volume_keywords.csv")
    if kws.empty:
        rows.append(["(no search_volume_keywords.csv)"])
    else:
        rows.extend(df_to_values(kws))
    return rows


def build_marketplace_tab(report: pd.DataFrame) -> pd.DataFrame:
    mp = safe_read_csv("out/marketplace_signal.csv")
    pc = safe_read_csv("out/printables_cults_signal.csv")
    if mp.empty and pc.empty:
        # fall back to report columns
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
        return out
    base = pc if not pc.empty else pd.DataFrame({"product": report["product"]})
    if not mp.empty:
        base = base.merge(mp, on="product", how="outer", suffixes=("", "_mp"))
    if "category" not in base.columns and "category" in report.columns:
        base = base.merge(
            report[["product", "category"]], on="product", how="left"
        )
    if "total_listings" not in base.columns:
        p = pd.to_numeric(base.get("printables_listing_count"), errors="coerce").fillna(0)
        c = pd.to_numeric(base.get("cults_listing_count"), errors="coerce").fillna(0)
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
    return base[cols]


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


def build_history_rows(report: pd.DataFrame, meta: dict) -> pd.DataFrame:
    df = report.copy()
    df["run_date"] = meta.get("run_date", "")
    df["run_id"] = meta.get("run_id", "")
    for c in HISTORY_COLS:
        if c not in df.columns:
            df[c] = ""
    return df[HISTORY_COLS]


def build_dashboard(
    rankings: pd.DataFrame,
    meta: dict,
    actions: list[str],
    local_kw: pd.DataFrame,
    history: pd.DataFrame,
    unmatched: list[str],
) -> list[list[Any]]:
    """Flat grid for Dashboard tab — charts overlay on specific ranges."""
    rows: list[list[Any]] = []
    run_date = meta.get("run_date", "")
    run_time = meta.get("run_time", "")
    # Row 1-4: status strip
    rows.append(["DEMAND MONITOR — DASHBOARD"])
    rows.append(
        [
            "Last updated:",
            f"{run_date} {run_time}",
            "run_id:",
            meta.get("run_id", ""),
        ]
    )
    # Freshness
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

    sources = meta.get("sources") or {}
    chips = []
    for name, key in [
        ("Search Volume", "search_volume"),
        ("Community", "community"),
        ("Marketplace", "marketplace"),
        ("Trends", "trends"),
        ("X", "x"),
        ("Reddit", "reddit"),
    ]:
        active = sources.get(key, True)
        # If sources dict incomplete, assume active unless in demand_unused
        unused = meta.get("demand_unused") or []
        if key == "reddit" and (
            "reddit_volume" in unused or "reddit_engagement" in unused
        ):
            active = False
        if key == "x" and ("x_volume" in unused or "x_engagement" in unused):
            active = False
        if key == "trends" and (
            "trends_interest" in unused or "momentum" in unused
        ):
            active = False
        if key == "search_volume" and (
            "search_volume" in unused or "volume_quality" in unused
        ):
            active = False
        if key == "community" and "community_downloads" in unused:
            active = False
        chips.append(f"{name}: {'active' if active else 'skipped'}")
    rows.append(["Sources this run:", " | ".join(chips)])

    # KPIs
    n_prod = int(meta.get("products_tracked") or len(rankings))
    top_p = ""
    if not rankings.empty and "priority_score" in rankings.columns:
        top_p = float(
            pd.to_numeric(rankings["priority_score"], errors="coerce").max() or 0
        )
    # churn: new in top 10 vs previous history run
    churn = "n/a (need ≥2 history runs)"
    if not history.empty and "run_id" in history.columns:
        runs = sorted(history["run_id"].dropna().unique())
        if len(runs) >= 2:
            cur_id, prev_id = runs[-1], runs[-2]
            cur_top = set(
                history[history["run_id"] == cur_id]
                .nsmallest(10, "rank")["product"]
                .tolist()
            ) if "rank" in history.columns else set()
            # if rank missing, use priority
            if not cur_top:
                cur_top = set(
                    history[history["run_id"] == cur_id]
                    .nlargest(10, "priority_score")["product"]
                    .tolist()
                )
            prev_top = set(
                history[history["run_id"] == prev_id]
                .nsmallest(10, "rank")["product"]
                .tolist()
            ) if "rank" in history.columns else set(
                history[history["run_id"] == prev_id]
                .nlargest(10, "priority_score")["product"]
                .tolist()
            )
            new_in = cur_top - prev_top
            churn = f"{len(new_in)} new in top 10 vs last run"
    local_n = len(local_kw) if not local_kw.empty else 0
    rows.append([])
    rows.append(
        [
            "KPI: products tracked",
            n_prod,
            "KPI: top priority_score",
            top_p,
            "KPI: top-10 churn",
            churn,
            "KPI: local-service keywords",
            local_n,
        ]
    )

    if unmatched:
        rows.append(
            [
                "UNMATCHED product names (check scanners vs products.yaml):",
                "; ".join(unmatched),
            ]
        )

    rows.append([])
    rows.append(["ACTION THIS WEEK"])
    for i, a in enumerate(actions, 1):
        rows.append([f"{i}.", a])

    rows.append([])
    rows.append(["TOP OPPORTUNITIES THIS WEEK"])
    # Chart data block starts at a known place — we'll also write a clean
    # table for the bar chart at columns A-F starting after header.
    top_cols = [
        "rank",
        "product",
        "category",
        "priority_score",
        "demand_score",
        "fit_score",
        "competition_score",
        "opportunity_score",
        "score_explanation",
    ]
    top = rankings.head(10).copy()
    for c in top_cols:
        if c not in top.columns:
            top[c] = ""
    rows.append(top_cols)
    for _, r in top.iterrows():
        rows.append([r[c] for c in top_cols])

    # Helper ranges for charts (Demand vs Fit scatter) — all products
    rows.append([])
    rows.append(["CHART DATA — Demand vs Fit (all products)"])
    rows.append(["product", "fit_score", "demand_score", "search_volume", "category"])
    for _, r in rankings.iterrows():
        rows.append(
            [
                r.get("product", ""),
                r.get("fit_score", ""),
                r.get("demand_score", ""),
                r.get("search_volume", ""),
                r.get("category", ""),
            ]
        )

    # Category averages for chart 3
    rows.append([])
    rows.append(["CHART DATA — Category avg priority"])
    rows.append(["category", "avg_priority_score", "n_products"])
    if not rankings.empty and "category" in rankings.columns:
        tmp = rankings.copy()
        tmp["priority_score"] = pd.to_numeric(tmp["priority_score"], errors="coerce")
        g = (
            tmp.groupby(tmp["category"].replace("", "(blank)"))
            .agg(avg_priority_score=("priority_score", "mean"), n_products=("product", "count"))
            .reset_index()
            .sort_values("avg_priority_score", ascending=False)
        )
        for _, r in g.iterrows():
            rows.append(
                [
                    r["category"],
                    round(float(r["avg_priority_score"]), 1)
                    if pd.notna(r["avg_priority_score"])
                    else "",
                    int(r["n_products"]),
                ]
            )

    # Local service mini panel
    rows.append([])
    rows.append(["LOCAL SERVICE (PHOENIX) — top keywords"])
    rows.append(["rank", "keyword", "search_volume", "cpc"])
    if not local_kw.empty:
        lk = local_kw.copy()
        if "search_volume" in lk.columns:
            lk["search_volume"] = pd.to_numeric(lk["search_volume"], errors="coerce")
            lk = lk.sort_values("search_volume", ascending=False).head(5)
        for i, (_, r) in enumerate(lk.iterrows(), 1):
            rows.append(
                [
                    r.get("rank", i),
                    r.get("keyword", ""),
                    r.get("search_volume", ""),
                    r.get("cpc", ""),
                ]
            )
    else:
        rows.append(["", "(no local service data)", "", ""])

    rows.append([])
    rows.append(
        [
            "Notes: Charts are bound to Product Rankings + History + the "
            "CHART DATA blocks above. Drill into Product Rankings / Scoring "
            "Detail for full columns."
        ]
    )
    return rows


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
    """Create missing tabs in TAB_ORDER; return title → sheetId."""
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
    """Append History rows; return number of rows appended."""
    existing = read_sheet_values(service, spreadsheet_id, "History")
    if not existing:
        values = df_to_values(new_df, HISTORY_COLS)
        clear_and_write(service, spreadsheet_id, "History", values)
        freeze_header(service, spreadsheet_id, sheet_id)
        return max(0, len(values) - 1)

    # existing[0] = header
    header = existing[0]
    # Map new_df to header order if possible
    cols = HISTORY_COLS
    new_values = df_to_values(new_df, cols)
    # Skip header from new_values
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


def add_dashboard_charts(
    service,
    spreadsheet_id: str,
    sheet_ids: dict[str, int],
    n_products: int,
    n_top: int = 10,
) -> None:
    """Create charts on Dashboard bound to live ranges."""
    dash_id = sheet_ids["Dashboard"]
    rank_id = sheet_ids["Product Rankings"]
    delete_all_charts(service, spreadsheet_id, dash_id)

    # Product Rankings columns (1-indexed in A1, 0-indexed in API):
    # A rank, B product, C category, D priority, E demand, F fit, G competition
    # Dashboard layout is variable; we use fixed chart data blocks written
    # after "CHART DATA — Demand vs Fit" and "CHART DATA — Category avg".
    # Simpler approach: bind Top 10 bar to Product Rankings!B2:D11
    # and Demand vs Fit scatter to Product Rankings fit/demand columns.

    requests_body = []

    # Chart 2: Top 10 Priority horizontal bar — Product Rankings product + priority
    # domain = product names (col B), series = priority (col D)
    end_row = min(1 + n_top, 1 + n_products)  # 0-index end exclusive in grid
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
                                "rowIndex": 28,
                                "columnIndex": 0,
                            },
                            "widthPixels": 560,
                            "heightPixels": 360,
                        }
                    },
                }
            }
        }
    )

    # Chart 1: Demand vs Fit scatter — Product Rankings fit (F) vs demand (E)
    requests_body.append(
        {
            "addChart": {
                "chart": {
                    "spec": {
                        "title": "Demand vs Fit",
                        "basicChart": {
                            "chartType": "SCATTER",
                            "legendPosition": "NO_LEGEND",
                            "axis": [
                                {"position": "BOTTOM_AXIS", "title": "fit_score"},
                                {"position": "LEFT_AXIS", "title": "demand_score"},
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
                                "rowIndex": 28,
                                "columnIndex": 6,
                            },
                            "widthPixels": 480,
                            "heightPixels": 360,
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
        LOG.info("Dashboard charts created (Top Priority + Demand vs Fit)")
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
    sv_matrix = build_search_volume_tab()
    market_df = build_marketplace_tab(report)
    local_matrix = build_local_service_tab()
    config_matrix = build_config_tab(products, local_svc)
    history_new = build_history_rows(report, meta)

    local_kw = safe_read_csv("out/local_service_keywords_phoenix_az.csv")

    # For actions we need existing history if any — dry-run uses empty
    history_existing = pd.DataFrame(columns=HISTORY_COLS)

    actions = compute_actions(rankings, history_existing, local_kw, meta)
    dashboard = build_dashboard(
        rankings, meta, actions, local_kw, history_existing, unmatched
    )

    LOG.info(
        "Prepared tabs: rankings=%d detail=%d history_new=%d actions=%d",
        len(rankings),
        len(detail),
        len(history_new),
        len(actions),
    )

    if dry_run:
        out_dir = Path("out/sheets_dry_run")
        out_dir.mkdir(parents=True, exist_ok=True)
        rankings.to_csv(out_dir / "product_rankings.csv", index=False)
        detail.to_csv(out_dir / "scoring_detail.csv", index=False)
        history_new.to_csv(out_dir / "history_append.csv", index=False)
        market_df.to_csv(out_dir / "marketplace.csv", index=False)
        (out_dir / "dashboard.txt").write_text(
            "\n".join("\t".join(str(c) for c in row) for row in dashboard)
        )
        (out_dir / "actions.json").write_text(json.dumps(actions, indent=2))
        (out_dir / "local_service.txt").write_text(
            "\n".join("\t".join(str(c) for c in row) for row in local_matrix)
        )
        LOG.info("Dry-run written to %s", out_dir)
        print("\n=== ACTION THIS WEEK (dry-run) ===")
        for a in actions:
            print(f"  • {a}")
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

    service = get_sheets_service(sa_path)
    sheet_ids = ensure_tabs(service, spreadsheet_id)

    # Read prior History for action rules (rising / drop)
    try:
        prev_vals = read_sheet_values(service, spreadsheet_id, "History")
        if prev_vals and len(prev_vals) > 1:
            header = prev_vals[0]
            history_existing = pd.DataFrame(prev_vals[1:], columns=header)
            # recompute actions with real history
            actions = compute_actions(rankings, history_existing, local_kw, meta)
            dashboard = build_dashboard(
                rankings, meta, actions, local_kw, history_existing, unmatched
            )
    except Exception as e:
        LOG.warning("Could not read prior History: %s", e)

    # Write regenerated tabs
    clear_and_write(service, spreadsheet_id, "Dashboard", dashboard)
    clear_and_write(
        service, spreadsheet_id, "Product Rankings", df_to_values(rankings, RANKINGS_COLS)
    )
    freeze_header(service, spreadsheet_id, sheet_ids["Product Rankings"])

    clear_and_write(
        service, spreadsheet_id, "Scoring Detail", df_to_values(detail)
    )
    freeze_header(service, spreadsheet_id, sheet_ids["Scoring Detail"])

    clear_and_write(service, spreadsheet_id, "Search Volume", sv_matrix)
    clear_and_write(
        service, spreadsheet_id, "Marketplace", df_to_values(market_df)
    )
    freeze_header(service, spreadsheet_id, sheet_ids["Marketplace"])

    clear_and_write(
        service, spreadsheet_id, "Local Service (Phoenix)", local_matrix
    )
    clear_and_write(service, spreadsheet_id, "Config", config_matrix)

    n_hist = append_history(
        service, spreadsheet_id, sheet_ids["History"], history_new
    )
    LOG.info("History appended %d rows", n_hist)

    if not skip_charts:
        add_dashboard_charts(
            service,
            spreadsheet_id,
            sheet_ids,
            n_products=len(rankings),
            n_top=min(10, len(rankings)),
        )

    print("\n=== ACTION THIS WEEK ===")
    for a in actions:
        print(f"  • {a}")
    print(
        f"\nSheets export complete → spreadsheet {spreadsheet_id}\n"
        f"  run_date={meta.get('run_date')}  history_rows_added={n_hist}"
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
