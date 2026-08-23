#!/usr/bin/env python3
"""
score_dashboard.py
------------------
Priority dashboard for Demand Monitor. Merges marketplace (required) plus
optional Google Trends CSVs (Reddit is retired), applies fit + Bambu Lab H2S heuristics,
and writes a ranked action table.

HOW TO RUN
  cd /workspace/demand-monitor
  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # or pyyaml pandas requests beautifulsoup4
  # 1) Live marketplace scan for one category (sleeps between requests):
  .venv/bin/python score_dashboard.py --scan-marketplace --category rad_power_bikes \\
      --marketplace-out out/marketplace_signal_rad.csv
  # 2) Score using that scan (reddit/trends optional; omitted = conservative demand):
  .venv/bin/python score_dashboard.py --config config/products.yaml \\
      --category rad_power_bikes \\
      --marketplace out/marketplace_signal_rad.csv \\
      --out out/dashboard_run.csv
  Optional: --trends out/trends_signal.csv  (Reddit is not used)
  Optional: --fetch-oem  (hits Rad Power Shopify products.json; never invents OOS)

Do not invent listing counts, Reddit post counts, Trends interest, or OOS flags.
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import tempfile
from typing import Optional

import pandas as pd
import yaml

# Reddit retired (no API). Demand is Trends + marketplace gap only.
WEIGHTS = {
    "trends_interest": 0.50,
    "trends_momentum": 0.20,
    "marketplace_gap": 0.30,
}

# When reddit + trends files are missing or empty, treat the missing social
# slice as a conservative 40/100 and keep only the marketplace_gap weight.
DEMAND_BASELINE_NO_SOCIAL = 40.0

# opportunity_score formula (0-100):
#   0.40 * demand_score + 0.35 * (100 - competition_score) + 0.25 * fit_score
OPP_W_DEMAND = 0.40
OPP_W_WHITESPACE = 0.35
OPP_W_FIT = 0.25

# priority_score formula (0-100):
#   0.35 * demand + 0.25 * opportunity + 0.20 * h2s_fit + 0.20 * fit
PRI_W_DEMAND = 0.35
PRI_W_OPP = 0.25
PRI_W_H2S = 0.20
PRI_W_FIT = 0.20

# ---------------------------------------------------------------------------
# FIT RUBRIC (printability / liability / model-specific sellability) → 0-100
# Base 70, then clamp 0-100 after adjustments:
#   Printability
#     +15  small snap-fit / clip / cap / hook (easy PETG/ASA/TPU, few supports)
#     +8   medium mount / adapter / holder
#     +0   large storage / console-sized part
#     -10  load-bearing (takes bike or cargo weight)
#     -20  electrical enclosure / battery *housing* (not a small cap)
#   Liability
#     -20  failure could drop the bike or a passenger
#     -15  battery / high-voltage safety (housing, not a dust cap)
#     -5   phone/device drop or moisture-trap weather cover
#     +5   purely convenience / rattle / dust / cosmetic
#   Sellability
#     +10  clearly Rad-platform-specific geometry
#     +0   generic e-bike accessory that still sells to Rad owners
#     -8   single-model caboose/niche accessory (tiny TAM)
# ---------------------------------------------------------------------------
#
# H2S FIT (Bambu Lab H2S: enclosed, large bed, PETG/ASA/TPU)
#   85-95  small snap parts
#   75-85  medium mounts
#   50-65  large storage
#   55-70  load-bearing hybrid
#   10-25  electrical / battery housing
# ---------------------------------------------------------------------------

DROP_NAME_RE = re.compile(
    r"(battery\s*(shell|hous|case|pack\s*cover)|passenger|kid\s*bar|child\s*bar|throttle\s*lever)",
    re.I,
)
DROP_KW_RE = re.compile(
    r"(battery\s*(shell|housing|case)|passenger\s*bar|kid\s*bar|child\s*bar|throttle\s*lever)",
    re.I,
)


def normalize(series: pd.Series) -> pd.Series:
    """Min-max to 0-100. Flat series → 50 (neutral), matching score_demand.py."""
    s = pd.to_numeric(series, errors="coerce")
    if s.dropna().empty:
        return pd.Series([50.0] * len(s), index=s.index)
    if s.max() == s.min():
        return s * 0 + 50.0
    return (s - s.min()) / (s.max() - s.min()) * 100.0


def _blob(name: str, keywords: list) -> str:
    return f"{name} {' '.join(keywords)}".lower()


def fit_and_h2s(name: str, keywords: list) -> tuple[float, float, str]:
    """Return (fit_score, h2s_fit, bucket_label) from the documented rubric."""
    text = _blob(name, keywords)
    fit = 70.0

    # --- printability / size / load ---
    if any(k in text for k in ("battery shell", "battery housing", "battery case")):
        fit += -20
        h2s, bucket = 18.0, "electrical/battery housing"
    elif any(k in text for k in ("kickstand foot", "kickstand widener", "kickstand base")):
        fit += -10  # load-bearing
        h2s, bucket = 62.0, "load-bearing hybrid"
    elif any(k in text for k in ("storage mount", "console", "field box", "step through box")):
        fit += 0
        h2s, bucket = 58.0, "large storage"
    elif any(
        k in text
        for k in (
            "phone mount",
            "display mount",
            "handlebar mount",
            "pannier",
            "rod holder",
            "fishing",
        )
    ):
        fit += 8
        if "pannier" in text:
            fit += -10  # some cargo load
            h2s, bucket = 76.0, "medium mounts"
        else:
            h2s, bucket = 80.0, "medium mounts"
    else:
        # default: small snap / cap / hook / clip / cover
        fit += 15
        h2s, bucket = 90.0, "small snap parts"

    # refine small-snap h2s inside the 85-95 band
    if bucket == "small snap parts":
        if "dust cap" in text or "charge port" in text or "charging port" in text:
            h2s = 93.0
        elif "anti-rattle" in text or "anti rattle" in text or "kickstand hook" in text or "kickstand clip" in text:
            h2s = 92.0
        elif "fuse" in text or "terminal" in text:
            h2s = 88.0  # small cap, not a housing
        elif "weather" in text or "sun cover" in text or "sun hood" in text or "screen cover" in text or "display cover" in text:
            h2s = 88.0
        elif "cargo" in text and "hook" in text:
            h2s = 88.0
        else:
            h2s = 90.0

    if bucket == "medium mounts":
        if "fishing" in text or "rod holder" in text:
            h2s = 78.0
        elif "phone" in text or "display mount" in text or "handlebar mount" in text:
            h2s = 80.0
        elif "pannier" in text:
            h2s = 76.0

    # --- liability ---
    if any(k in text for k in ("kickstand foot", "kickstand widener", "kickstand base")):
        fit += -20
    if any(k in text for k in ("battery shell", "battery housing")):
        fit += -15
    if any(k in text for k in ("phone mount", "weather", "sun cover", "sun hood", "rain cap")):
        fit += -5
    if any(k in text for k in ("dust", "rattle", "fuse cover", "terminal", "cargo net", "cargo hook")):
        fit += 5

    # --- sellability ---
    if "rad" in text:
        fit += 10
    if any(k in text for k in ("caboose", "fishing rod")):
        fit += -8

    fit = max(0.0, min(100.0, fit))
    h2s = max(0.0, min(100.0, h2s))
    return round(fit, 1), round(h2s, 1), bucket


def is_drop(name: str, keywords: list) -> bool:
    if DROP_NAME_RE.search(name or ""):
        return True
    for kw in keywords or []:
        if DROP_KW_RE.search(kw):
            return True
    return False


def load_optional_csv(path: Optional[str]) -> Optional[pd.DataFrame]:
    if not path:
        return None
    if not os.path.isfile(path):
        return None
    df = pd.read_csv(path)
    if df.empty:
        return None
    return df


def marketplace_scan_failed(row) -> bool:
    """True when every listing column is ERR / empty / non-numeric (not a real 0)."""
    cols = [c for c in row.index if str(c).endswith("_listing_count")]
    if not cols:
        return True
    vals = []
    for c in cols:
        v = row[c]
        if pd.isna(v) or v == "" or str(v).upper() == "ERR":
            continue
        try:
            float(v)
            vals.append(v)
        except (TypeError, ValueError):
            continue
    return len(vals) == 0


def choose_action(row, have_reddit: bool, have_trends: bool) -> str:
    # Apply in the specified order.
    if row["drop_flag"]:
        return "DROP?"
    if (not have_trends) and row["mp_failed"]:
        return "NEEDS DATA"
    if (
        row["priority_score"] >= 70
        and row["h2s_fit"] >= 70
        and row["competition_score"] <= 70
        and not row["drop_flag"]
    ):
        return "PROTOTYPE"
    if row["priority_score"] >= 60 and row["action_tmp"] != "PROTOTYPE":
        # second check uses the would-be prototype; we already returned
        return "CLOSEST"
    return "WATCH"
    # LOCAL is reserved for parts we would not ship; none of the Rad SKUs qualify.


def fetch_oem_notes(products: list) -> dict:
    """Best-effort Shopify collection dump. Returns product → short OOS note or ''."""
    import requests

    urls = [
        "https://www.radpowerbikes.com/collections/spare-parts/products.json?limit=250",
        "https://www.radpowerbikes.com/collections/accessories/products.json?limit=250",
    ]
    items = []
    headers = {"User-Agent": "Mozilla/5.0 (compatible; printshop-demand-scan/0.1; research use)"}
    for url in urls:
        try:
            resp = requests.get(url, headers=headers, timeout=20)
            if resp.status_code != 200:
                print(f"  [warn] OEM fetch HTTP {resp.status_code} for {url}")
                continue
            data = resp.json()
            items.extend(data.get("products") or [])
        except Exception as e:
            print(f"  [warn] OEM fetch failed for {url}: {e}")
    print(f"  OEM catalog rows fetched: {len(items)}")

    notes = {p["name"]: "" for p in products}
    if not items:
        return notes

    def avail(p):
        variants = p.get("variants") or []
        if not variants:
            return None
        return any(bool(v.get("available")) for v in variants)

    # Keyword → tokens we look for on official titles (conservative).
    token_map = [
        (["fuse", "terminal"], ["fuse", "terminal"]),
        (["charging port", "charge port", "dust cap"], ["charge port", "charging port", "dust cap"]),
        (["cargo net", "cargo hook"], ["cargo net", "net hook"]),
        (["kickstand foot", "kickstand widener"], ["kickstand"]),
        (["phone mount", "display mount"], ["phone mount", "display mount", "handlebar mount"]),
        (["anti-rattle", "kickstand hook", "kickstand clip"], ["kickstand"]),
        (["display cover", "sun cover", "sun hood", "screen cover"], ["display cover", "screen cover"]),
        (["pannier"], ["pannier"]),
        (["storage mount", "console", "field box"], ["console", "storage", "field box"]),
        (["fishing", "rod holder", "caboose"], ["fishing", "rod", "caboose"]),
    ]

    for prod in products:
        text = _blob(prod["name"], prod.get("keywords") or [])
        related = []
        for needles, title_tokens in token_map:
            if any(n in text for n in needles):
                for it in items:
                    title = (it.get("title") or "").lower()
                    if any(t in title for t in title_tokens):
                        related.append(it)
        # de-dupe by id
        seen = set()
        uniq = []
        for it in related:
            i = it.get("id")
            if i in seen:
                continue
            seen.add(i)
            uniq.append(it)
        oos = [it for it in uniq if avail(it) is False]
        if oos:
            titles = ", ".join((it.get("title") or "?")[:60] for it in oos[:3])
            notes[prod["name"]] = f"Related official SKU unavailable (OOS from live catalog): {titles}."
    return notes


def write_filtered_config(src_path: str, dest_path: str, category: Optional[str]) -> int:
    with open(src_path) as f:
        cfg = yaml.safe_load(f)
    if category:
        cfg["products"] = [p for p in cfg.get("products", []) if p.get("category") == category]
    with open(dest_path, "w") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)
    return len(cfg["products"])


def run_marketplace_scan(config_path: str, out_path: str, category: Optional[str]) -> str:
    import marketplace_scan

    if category:
        fd, tmp = tempfile.mkstemp(prefix="products_rad_", suffix=".yaml")
        os.close(fd)
        n = write_filtered_config(config_path, tmp, category)
        print(f"Scanning {n} products in category={category}")
        try:
            marketplace_scan.scan(tmp, out_path)
        finally:
            os.remove(tmp)
    else:
        marketplace_scan.scan(config_path, out_path)
    return out_path


def score(
    config_path: str,
    marketplace_path: str,
    out_path: str,
    category: Optional[str],
    reddit_path: Optional[str],
    trends_path: Optional[str],
    oem_notes: Optional[dict],
    marketplace_all_zero_note: Optional[str],
):
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    products = cfg.get("products") or []
    if category:
        products = [p for p in products if p.get("category") == category]
    if not products:
        raise SystemExit(f"No products found for category={category!r}")

    mp = pd.read_csv(marketplace_path)
    reddit = load_optional_csv(reddit_path)
    trends = load_optional_csv(trends_path)
    have_reddit = reddit is not None and "reddit_matching_posts" in reddit.columns
    have_trends = trends is not None and "trends_avg_interest_0_100" in trends.columns

    meta = pd.DataFrame(
        [
            {
                "product": p["name"],
                "category": p.get("category", ""),
                "keywords": p.get("keywords") or [],
            }
            for p in products
        ]
    )
    df = meta.merge(mp, on="product", how="left")
    if have_reddit:
        df = df.merge(reddit, on="product", how="left")
    if have_trends:
        df = df.merge(trends, on="product", how="left")

    listing_cols = [c for c in df.columns if c.endswith("_listing_count")]
    raw_listing = df[listing_cols].copy() if listing_cols else pd.DataFrame(index=df.index)
    df["mp_failed"] = df.apply(marketplace_scan_failed, axis=1)

    for c in listing_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    df["total_listings"] = df[listing_cols].sum(axis=1) if listing_cols else 0

    # Competition: MORE listings = HIGHER score. Flat/all-zero → 50.
    df["competition_score"] = normalize(df["total_listings"]).round(1)
    # Gap rewards whitespace (low listings).
    df["marketplace_gap"] = (100.0 - df["competition_score"]).clip(0, 100)

    if have_reddit and have_trends:
        df["reddit_matching_posts"] = df["reddit_matching_posts"].fillna(0)
        df["reddit_total_upvotes"] = df["reddit_total_upvotes"].fillna(0)
        df["reddit_total_comments"] = df["reddit_total_comments"].fillna(0)
        df["trends_avg_interest_0_100"] = df["trends_avg_interest_0_100"].fillna(0)
        df["trends_recent_vs_prior_pct_change"] = df["trends_recent_vs_prior_pct_change"].fillna(0)
        df["score_reddit_volume"] = normalize(df["reddit_matching_posts"])
        df["score_reddit_engagement"] = normalize(
            df["reddit_total_upvotes"] + df["reddit_total_comments"]
        )
        df["score_trends_interest"] = normalize(df["trends_avg_interest_0_100"])
        df["score_trends_momentum"] = normalize(df["trends_recent_vs_prior_pct_change"])
        sat = normalize(df["total_listings"])
        df["score_marketplace_gap"] = (
            df["score_trends_interest"] * 0.6 + (100 - sat) * 0.4
        )
        df["demand_score"] = (
            df["score_reddit_volume"] * WEIGHTS["reddit_volume"]
            + df["score_reddit_engagement"] * WEIGHTS["reddit_engagement"]
            + df["score_trends_interest"] * WEIGHTS["trends_interest"]
            + df["score_trends_momentum"] * WEIGHTS["trends_momentum"]
            + df["score_marketplace_gap"] * WEIGHTS["marketplace_gap"]
        ).round(1)
        demand_mode = "full"
    else:
        # Conservative: 40 baseline on the missing social weight (0.85) + real gap (0.15).
        social_w = 1.0 - WEIGHTS["marketplace_gap"]
        df["demand_score"] = (
            DEMAND_BASELINE_NO_SOCIAL * social_w
            + df["marketplace_gap"] * WEIGHTS["marketplace_gap"]
        ).round(1)
        demand_mode = "baseline"

    fit_rows = [fit_and_h2s(p["name"], p.get("keywords") or []) for p in products]
    df["fit_score"] = [r[0] for r in fit_rows]
    df["h2s_fit"] = [r[1] for r in fit_rows]
    df["h2s_bucket"] = [r[2] for r in fit_rows]
    df["drop_flag"] = [is_drop(p["name"], p.get("keywords") or []) for p in products]

    # opportunity_score = 0.40*demand + 0.35*(100-competition) + 0.25*fit
    df["opportunity_score"] = (
        OPP_W_DEMAND * df["demand_score"]
        + OPP_W_WHITESPACE * (100.0 - df["competition_score"])
        + OPP_W_FIT * df["fit_score"]
    ).round(1)

    # priority_score = 0.35*demand + 0.25*opportunity + 0.20*h2s_fit + 0.20*fit
    df["priority_score"] = (
        PRI_W_DEMAND * df["demand_score"]
        + PRI_W_OPP * df["opportunity_score"]
        + PRI_W_H2S * df["h2s_fit"]
        + PRI_W_FIT * df["fit_score"]
    ).round(1)

    df["action_tmp"] = ""
    actions = []
    for _, row in df.iterrows():
        actions.append(choose_action(row, have_reddit, have_trends))
    df["action"] = actions

    oem_notes = oem_notes or {}
    explanations = []
    for _, row in df.iterrows():
        parts = []
        if demand_mode == "baseline":
            missing = []
            if not have_reddit:
                missing.append("Reddit")
            if not have_trends:
                missing.append("Google Trends")
            parts.append(
                f"Demand uses a conservative {DEMAND_BASELINE_NO_SOCIAL:.0f} baseline "
                f"plus marketplace gap (weight {WEIGHTS['marketplace_gap']:.2f}); "
                f"{' and '.join(missing)} were not scanned (no API keys / skipped), "
                f"not estimated."
            )
        else:
            parts.append(
                "Demand uses live Reddit + Trends + marketplace weights from score_demand.py."
            )
        if row["mp_failed"]:
            parts.append("Marketplace scan failed or was empty (ERR); listing counts were not invented.")
        else:
            counts = []
            for c in listing_cols:
                raw = raw_listing.loc[row.name, c] if c in raw_listing.columns else "n/a"
                counts.append(f"{c.replace('_listing_count','')}={raw}")
            parts.append(
                f"Marketplace counts are from the live scrape ({', '.join(counts)}; "
                f"total_listings={int(row['total_listings'])})."
            )
        if marketplace_all_zero_note:
            parts.append(marketplace_all_zero_note)
        parts.append(
            f"H2S bucket: {row['h2s_bucket']} (h2s_fit={row['h2s_fit']}); "
            f"fit from printability/liability/sellability rubric."
        )
        oem = oem_notes.get(row["product"]) or ""
        if oem:
            parts.append(oem)
        explanations.append(" ".join(parts))
    df["score_explanation"] = explanations

    out_cols = [
        "product",
        "category",
        "priority_score",
        "demand_score",
        "fit_score",
        "h2s_fit",
        "competition_score",
        "opportunity_score",
        "score_explanation",
        "action",
    ]
    out = df[out_cols].sort_values("priority_score", ascending=False)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    out.to_csv(out_path, index=False)

    print("\n=== DEMAND MONITOR DASHBOARD ===\n")
    # Wide explanation truncated for stdout readability; full text is in the CSV.
    show = out.copy()
    show["score_explanation"] = show["score_explanation"].str.slice(0, 140) + "…"
    pd.set_option("display.max_colwidth", 160)
    pd.set_option("display.width", 220)
    print(out.to_string(index=False))
    print(f"\nWrote {len(out)} rows to {out_path}")
    print("Actions:", out.groupby("action").size().to_dict())
    return out


def detect_all_zero_or_stale(marketplace_path: str) -> Optional[str]:
    if not os.path.isfile(marketplace_path):
        return None
    df = pd.read_csv(marketplace_path)
    cols = [c for c in df.columns if c.endswith("_listing_count")]
    if not cols:
        return "Marketplace CSV had no listing columns."
    numeric = df[cols].apply(pd.to_numeric, errors="coerce")
    err_all = True
    for c in cols:
        raw = df[c].astype(str)
        if not raw.str.upper().isin(["ERR", "NAN", ""]).all():
            err_all = False
    if err_all:
        return "All marketplace lookups returned ERR; selectors or HTTP failed. Counts not invented."
    if numeric.fillna(0).to_numpy().sum() == 0:
        return (
            "Printables/MakerWorld listing counts were 0 for every SKU; "
            "CSS selectors may be stale. Recorded as 0, not replaced with estimates."
        )
    return None


def main():
    parser = argparse.ArgumentParser(description="Demand Monitor dashboard scorer")
    parser.add_argument("--config", default="config/products.yaml")
    parser.add_argument("--category", default=None)
    parser.add_argument("--marketplace", default="out/marketplace_signal_rad.csv")
    parser.add_argument("--reddit", default=None)
    parser.add_argument("--trends", default=None)
    parser.add_argument("--out", default="out/dashboard_run.csv")
    parser.add_argument("--scan-marketplace", action="store_true")
    parser.add_argument("--marketplace-out", default=None)
    parser.add_argument("--fetch-oem", action="store_true")
    args = parser.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    os.chdir(here)
    if not os.path.isabs(args.config):
        args.config = os.path.join(here, args.config)

    mp_out = args.marketplace_out or args.marketplace
    if args.scan_marketplace:
        run_marketplace_scan(args.config, mp_out, args.category)
        args.marketplace = mp_out

    oem_notes = None
    if args.fetch_oem:
        with open(args.config) as f:
            cfg = yaml.safe_load(f)
        products = cfg.get("products") or []
        if args.category:
            products = [p for p in products if p.get("category") == args.category]
        print("Fetching official Rad Power spare-parts / accessories JSON…")
        oem_notes = fetch_oem_notes(products)

    stale = detect_all_zero_or_stale(args.marketplace)
    score(
        config_path=args.config,
        marketplace_path=args.marketplace,
        out_path=args.out,
        category=args.category,
        reddit_path=args.reddit,
        trends_path=args.trends,
        oem_notes=oem_notes,
        marketplace_all_zero_note=stale,
    )


if __name__ == "__main__":
    main()
