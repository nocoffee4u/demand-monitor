#!/usr/bin/env python3
"""
score_demand.py
----------------
Merges signal CSVs and ranks products with transparent scores:

  demand_score       0–100  Quality-weighted pull (not raw volume alone)
  competition_score  0–100  How crowded is supply
  fit_score          0–100  Manufacturing + customer-clarity fit (Bambu FDM stage)
  opportunity_score  0–100  Demand vs competition
  priority_score     0–100  Primary rank = opportunity × fit  (own products first)

Demand quality factors (rule-based, explainable):
  intent, specificity, problem intensity, momentum, volume_quality,
  plus community engagement / trends / X / Reddit when present.

Empty optional sources (Reddit, X, Trends) redistribute weights so missing
data never invents signal or breaks ranking.

USAGE:
  python3 score_demand.py
  python3 score_demand.py --out out/demand_report.csv

Optional per-product overrides in config/products.yaml under `fit:`.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from typing import Iterable

import pandas as pd
import yaml

# ---------------------------------------------------------------------------
# Weights
# ---------------------------------------------------------------------------

# Quality-first demand (sums ~1.0 before empty-source redistribution)
DEMAND_WEIGHTS = {
    "volume_quality": 0.22,  # log volume × specificity (not raw volume)
    "intent": 0.16,
    "specificity": 0.16,
    "problem_intensity": 0.10,
    "momentum": 0.08,
    "community_downloads": 0.10,
    "community_makes": 0.07,
    "community_likes": 0.04,
    "trends_interest": 0.03,
    "x_volume": 0.02,
    "x_engagement": 0.01,
    "reddit_volume": 0.005,
    "reddit_engagement": 0.005,
}

COMPETITION_WEIGHTS = {
    "marketplace_listings": 0.65,
    "ads_competition": 0.15,
    "incumbent_strength": 0.20,
}

FIT_WEIGHTS = {
    "fdm_fit": 0.35,
    "material_fit": 0.20,
    "customer_clarity": 0.30,
    "support_burden": 0.15,  # higher score = lower support burden
}

OPPORTUNITY_COMPETITION_FLOOR = 12.0
OPPORTUNITY_RATIO_BLEND = 0.65

# priority = opportunity * (PRIORITY_FIT_FLOOR + (1-floor) * fit/100)
PRIORITY_FIT_FLOOR = 0.40

# Optional config for product fit overrides
DEFAULT_PRODUCTS_CONFIG = "config/products.yaml"


# ---------------------------------------------------------------------------
# Lexicons (simple, maintainable)
# ---------------------------------------------------------------------------

BUYING_INTENT = re.compile(
    r"\b(replace|replacement|cover|cap|mount|clip|hook|guard|protector|"
    r"bracket|holder|adapter|upgrade|kit|spare|widener|extender)\b",
    re.I,
)
PROBLEM_LANG = re.compile(
    r"\b(break|broken|crack|fail|loose|dust|fuse|crash|protect|guard|"
    r"replace|wear|damage|missing|lost|rattle|wobble)\b",
    re.I,
)
BRAND_PLATFORM = re.compile(
    r"\b(rad\s*power|radpower|radrunner|radrover|rzr|polaris|can[\s-]?am|"
    r"gopro|action\s*cam|utv|sxs|side[\s-]?by[\s-]?side|mtb|"
    r"mountain\s*bike|ebike|e[\s-]?bike|fpv|vtx|walksnail|"
    r"dji|betafpv)\b",
    re.I,
)
BROAD_GENERIC = re.compile(
    r"\b(car\s*phone\s*(holder|mount)|phone\s*holder|phone\s*mount|"
    r"bike\s*phone\s*mount|handlebar\s*phone\s*mount|"
    r"dash\s*phone\s*mount|magnetic\s*car\s*mount|"
    r"gopro\s*mount|action\s*camera)\b",
    re.I,
)
# Likely hard for early FDM product shop
POOR_FDM = re.compile(
    r"\b(resin|sla|dlp|metal|cnc|injection|silicone|overmold|"
    r"multi[\s-]?body|assembly\s*kit|wiring\s*harness\s*full|"
    r"full\s*panel|large\s*enclosure)\b",
    re.I,
)
FDM_FRIENDLY = re.compile(
    r"\b(mount|clip|cover|cap|guard|protector|bracket|hook|holder|"
    r"spacer|bushing|foot|pad|plug|guide)\b",
    re.I,
)
HIGH_SUPPORT = re.compile(
    r"\b(kit|multi|adjustable|universal\s*fit|custom|parametric|"
    r"harness|wiring|electronics|assembly)\b",
    re.I,
)
STOP = {
    "the",
    "a",
    "an",
    "for",
    "of",
    "and",
    "or",
    "to",
    "in",
    "on",
    "with",
    "by",
    "3d",
    "print",
    "printed",
}


def normalize(series: pd.Series) -> pd.Series:
    """Min-max to 0–100. Flat series → 50 (neutral)."""
    s = pd.to_numeric(series, errors="coerce")
    if s.isna().all():
        return pd.Series([50.0] * len(series), index=series.index)
    s = s.fillna(s.median() if s.notna().any() else 0)
    lo, hi = float(s.min()), float(s.max())
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


def _content_tokens(text: str) -> list[str]:
    return [
        t
        for t in re.split(r"\W+", (text or "").lower())
        if t and len(t) > 2 and t not in STOP
    ]


def load_product_meta(config_path: str) -> dict[str, dict]:
    """name → product block from products.yaml (keywords, fit overrides, category)."""
    if not os.path.exists(config_path):
        return {}
    try:
        with open(config_path) as f:
            cfg = yaml.safe_load(f) or {}
    except Exception as e:
        print(f"  [warn] products config: {e}")
        return {}
    out = {}
    for p in cfg.get("products") or []:
        name = p.get("name")
        if name:
            out[name] = p
    return out


# ---------------------------------------------------------------------------
# Demand quality scores (per row)
# ---------------------------------------------------------------------------

def score_intent(name: str, best_kw: str, keywords: list[str], cpc: float) -> tuple[float, str]:
    blob = " ".join([name, best_kw] + keywords)
    score = 40.0
    notes = []
    if BUYING_INTENT.search(blob):
        score += 25
        notes.append("buying_language")
    if BRAND_PLATFORM.search(blob):
        score += 15
        notes.append("platform_specific")
    if BROAD_GENERIC.search(best_kw or name):
        score -= 30
        notes.append("broad_generic_penalty")
    # CPC proxy: higher paid CPC → more commercial (cap influence)
    if cpc and cpc > 0:
        score += min(15.0, cpc * 1.5)
        notes.append(f"cpc={cpc:.2f}")
    # Replacement / spare intent
    if re.search(r"\b(replace|replacement|spare)\b", blob, re.I):
        score += 10
        notes.append("replacement")
    return max(0.0, min(100.0, score)), ",".join(notes) or "neutral"


def score_specificity(name: str, best_kw: str, keywords: list[str], category: str) -> tuple[float, str]:
    blob = " ".join([name, best_kw] + keywords)
    score = 35.0
    notes = []
    if BRAND_PLATFORM.search(blob):
        score += 30
        notes.append("brand_or_platform")
    # Distinctive tokens in best keyword
    toks = _content_tokens(best_kw or name)
    distinctive = [t for t in toks if t not in {"bike", "mount", "phone", "car", "clip", "guard"}]
    if len(distinctive) >= 3:
        score += 20
        notes.append("narrow_phrase")
    elif len(distinctive) <= 1:
        score -= 20
        notes.append("vague_phrase")
    if BROAD_GENERIC.search(best_kw or ""):
        score -= 35
        notes.append("generic_winner_kw")
    # Category hint: rad_power / atv more specific than automotive generic
    if category in ("rad_power_bikes", "drone_fpv", "atv_utv"):
        score += 10
        notes.append(f"cat={category}")
    if category == "automotive" and not BRAND_PLATFORM.search(blob):
        score -= 10
        notes.append("generic_auto")
    return max(0.0, min(100.0, score)), ",".join(notes) or "neutral"


def score_problem_intensity(
    name: str, keywords: list[str], makes: float, reddit_eng: float
) -> tuple[float, str]:
    blob = " ".join([name] + keywords)
    score = 40.0
    notes = []
    if PROBLEM_LANG.search(blob):
        score += 30
        notes.append("problem_language")
    if re.search(r"\b(fuse|dust|crash|bash|protect|guard|kickstand)\b", blob, re.I):
        score += 10
        notes.append("wear_or_protect_use")
    # Community makes = people actually printing → validated need (light)
    if makes and makes > 0:
        score += min(15.0, makes * 0.4)
        notes.append(f"makes={int(makes)}")
    if reddit_eng and reddit_eng > 0:
        score += min(10.0, reddit_eng * 0.2)
        notes.append("reddit_eng")
    return max(0.0, min(100.0, score)), ",".join(notes) or "neutral"


def score_volume_quality(volume: float, specificity: float) -> float:
    """Log volume scaled by specificity so 50k generic doesn't dominate."""
    import math

    vol = max(0.0, float(volume or 0))
    # specificity 0–100 → factor 0.25–1.0
    factor = 0.25 + 0.75 * (specificity / 100.0)
    return math.log1p(vol) * factor


# ---------------------------------------------------------------------------
# Fit scores
# ---------------------------------------------------------------------------

def score_fit_row(
    name: str,
    keywords: list[str],
    category: str,
    fit_override: dict | None,
) -> dict:
    """Return fdm_fit, material_fit, customer_clarity, support_burden (higher=easier)."""
    blob = " ".join([name] + keywords)
    ov = fit_override or {}

    # FDM
    if "fdm_fit" in ov:
        fdm = float(ov["fdm_fit"])
        fdm_note = "override"
    else:
        fdm = 75.0
        fdm_note = "default_fdm"
        if FDM_FRIENDLY.search(blob):
            fdm = 90.0
            fdm_note = "fdm_friendly_geometry"
        if POOR_FDM.search(blob):
            fdm = 20.0
            fdm_note = "needs_non_fdm_or_complex"

    # Materials (current stack: PLA/PETG/CF nylons)
    if "material_fit" in ov:
        mat = float(ov["material_fit"])
        mat_note = "override"
    else:
        mat = 85.0
        mat_note = "pla_petg_ok"
        if re.search(r"\b(metal|titanium|aluminum\s*print)\b", blob, re.I):
            mat = 15.0
            mat_note = "metal"
        elif re.search(r"\b(resin|sla)\b", blob, re.I):
            mat = 25.0
            mat_note = "resin"
        elif re.search(r"\b(flexible|tpu|rubber)\b", blob, re.I):
            mat = 70.0
            mat_note = "tpu_possible"

    # Customer clarity
    if "customer_clarity" in ov:
        clarity = float(ov["customer_clarity"])
        clarity_note = "override"
    else:
        clarity = 45.0
        clarity_note = "mid"
        if BRAND_PLATFORM.search(blob):
            clarity = 90.0
            clarity_note = "clear_platform"
        elif category in ("rad_power_bikes", "drone_fpv", "atv_utv", "mtb_general"):
            clarity = 70.0
            clarity_note = f"cat={category}"
        if category == "automotive" and not BRAND_PLATFORM.search(blob):
            clarity = 35.0
            clarity_note = "vague_auto"
        if BROAD_GENERIC.search(blob):
            clarity = min(clarity, 30.0)
            clarity_note = "generic_use_case"

    # Support burden (score high = low burden)
    if "support_burden" in ov:
        support = float(ov["support_burden"])
        support_note = "override"
    else:
        support = 80.0
        support_note = "simple_part"
        if HIGH_SUPPORT.search(blob):
            support = 40.0
            support_note = "higher_support_risk"
        if FDM_FRIENDLY.search(blob) and not HIGH_SUPPORT.search(blob):
            support = 90.0
            support_note = "single_piece_likely"
        if category == "automotive" and "universal" in blob.lower():
            support = 30.0
            support_note = "fitment_questions_likely"

    flags = [fdm_note, mat_note, clarity_note, support_note]
    return {
        "fdm_fit": max(0.0, min(100.0, fdm)),
        "material_fit": max(0.0, min(100.0, mat)),
        "customer_clarity": max(0.0, min(100.0, clarity)),
        "support_burden": max(0.0, min(100.0, support)),
        "fit_flags": ";".join(flags),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(
    reddit_path: str,
    trends_path: str,
    marketplace_path: str,
    out_path: str,
    x_path: str | None = None,
    search_volume_path: str | None = None,
    community_path: str | None = None,
    products_config: str = DEFAULT_PRODUCTS_CONFIG,
) -> None:
    product_meta = load_product_meta(products_config)

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

    if "search_volume_best_keyword" not in df.columns:
        df["search_volume_best_keyword"] = ""
    if "category" not in df.columns:
        df["category"] = ""

    # --- Quality dimensions ------------------------------------------------
    intent_scores = []
    intent_notes = []
    spec_scores = []
    spec_notes = []
    prob_scores = []
    prob_notes = []
    vol_quality = []
    fit_rows = []

    for _, row in df.iterrows():
        name = str(row.get("product") or "")
        meta = product_meta.get(name) or {}
        kws = list(meta.get("keywords") or []) + list(
            meta.get("search_volume_keywords") or []
        )
        best_kw = str(row.get("search_volume_best_keyword") or "")
        cat = str(row.get("category") or meta.get("category") or "")
        cpc = float(row.get("cpc_avg") or 0)
        makes = float(row.get("community_makes") or 0)
        reddit_eng = float(row.get("reddit_total_upvotes") or 0) + float(
            row.get("reddit_total_comments") or 0
        )

        intent, inote = score_intent(name, best_kw, kws, cpc)
        spec, snote = score_specificity(name, best_kw, kws, cat)
        prob, pnote = score_problem_intensity(name, kws, makes, reddit_eng)
        vq = score_volume_quality(float(row.get("search_volume") or 0), spec)
        fit = score_fit_row(name, kws, cat, meta.get("fit"))

        intent_scores.append(intent)
        intent_notes.append(inote)
        spec_scores.append(spec)
        spec_notes.append(snote)
        prob_scores.append(prob)
        prob_notes.append(pnote)
        vol_quality.append(vq)
        fit_rows.append(fit)

    df["raw_intent"] = intent_scores
    df["intent_notes"] = intent_notes
    df["raw_specificity"] = spec_scores
    df["specificity_notes"] = spec_notes
    df["raw_problem_intensity"] = prob_scores
    df["problem_notes"] = prob_notes
    df["raw_volume_quality"] = vol_quality
    df["fdm_fit"] = [r["fdm_fit"] for r in fit_rows]
    df["material_fit"] = [r["material_fit"] for r in fit_rows]
    df["customer_clarity"] = [r["customer_clarity"] for r in fit_rows]
    df["support_burden"] = [r["support_burden"] for r in fit_rows]
    df["fit_flags"] = [r["fit_flags"] for r in fit_rows]

    # Normalize raw quality + signals
    df["n_volume_quality"] = normalize(df["raw_volume_quality"])
    df["n_intent"] = df["raw_intent"]  # already 0–100 absolute
    df["n_specificity"] = df["raw_specificity"]
    df["n_problem_intensity"] = df["raw_problem_intensity"]
    df["n_momentum"] = normalize(df["trends_recent_vs_prior_pct_change"])
    df["n_community_downloads"] = normalize(df["community_downloads"])
    df["n_community_makes"] = normalize(df["community_makes"])
    df["n_community_likes"] = normalize(df["community_likes"])
    df["n_trends_interest"] = normalize(df["trends_avg_interest_0_100"])
    df["n_reddit_volume"] = normalize(df["reddit_matching_posts"])
    df["n_reddit_engagement"] = normalize(
        df["reddit_total_upvotes"] + df["reddit_total_comments"]
    )
    df["n_x_volume"] = normalize(df["x_matching_posts"])
    df["n_x_engagement"] = normalize(
        df["x_total_likes"] + df["x_total_replies"] + df["x_total_reposts"]
    )
    df["n_marketplace_listings"] = normalize(df["total_listings"])
    if df["ads_competition_avg"].sum() == 0:
        df["n_ads_competition"] = 50.0
    else:
        df["n_ads_competition"] = normalize(df["ads_competition_avg"])
    df["n_incumbent_strength"] = normalize(df["community_downloads"])

    # Dampen community downloads when specificity is low (generic viral mounts)
    df["n_community_downloads_adj"] = (
        df["n_community_downloads"] * (0.35 + 0.65 * df["n_specificity"] / 100.0)
    )

    # --- Demand ------------------------------------------------------------
    demand_w = dict(DEMAND_WEIGHTS)
    demand_unused: list[str] = []
    if _signal_empty(df, ["search_volume"]) and _signal_empty(df, ["raw_volume_quality"]):
        demand_unused.append("volume_quality")
    if _signal_empty(df, ["community_downloads", "community_makes", "community_likes"]):
        demand_unused.extend(
            ["community_downloads", "community_makes", "community_likes"]
        )
    if _signal_empty(
        df, ["trends_avg_interest_0_100", "trends_recent_vs_prior_pct_change"]
    ):
        demand_unused.extend(["trends_interest", "momentum"])
    elif _signal_empty(df, ["trends_recent_vs_prior_pct_change"]):
        demand_unused.append("momentum")
    if _signal_empty(
        df,
        ["reddit_matching_posts", "reddit_total_upvotes", "reddit_total_comments"],
    ):
        demand_unused.extend(["reddit_volume", "reddit_engagement"])
    if _signal_empty(
        df, ["x_matching_posts", "x_total_likes", "x_total_replies", "x_total_reposts"]
    ):
        demand_unused.extend(["x_volume", "x_engagement"])
    demand_w = _redistribute(demand_w, demand_unused)

    demand_cols = {
        "volume_quality": "n_volume_quality",
        "intent": "n_intent",
        "specificity": "n_specificity",
        "problem_intensity": "n_problem_intensity",
        "momentum": "n_momentum",
        "community_downloads": "n_community_downloads_adj",
        "community_makes": "n_community_makes",
        "community_likes": "n_community_likes",
        "trends_interest": "n_trends_interest",
        "x_volume": "n_x_volume",
        "x_engagement": "n_x_engagement",
        "reddit_volume": "n_reddit_volume",
        "reddit_engagement": "n_reddit_engagement",
    }

    demand_score = pd.Series(0.0, index=df.index)
    for key, col in demand_cols.items():
        w = demand_w.get(key, 0.0)
        contrib = df[col] * w
        df[f"contrib_demand_{key}"] = contrib.round(2)
        demand_score = demand_score + contrib
    df["demand_score"] = demand_score.round(1)

    # --- Competition -------------------------------------------------------
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

    # --- Fit ---------------------------------------------------------------
    fit_score = (
        df["fdm_fit"] * FIT_WEIGHTS["fdm_fit"]
        + df["material_fit"] * FIT_WEIGHTS["material_fit"]
        + df["customer_clarity"] * FIT_WEIGHTS["customer_clarity"]
        + df["support_burden"] * FIT_WEIGHTS["support_burden"]
    )
    df["contrib_fit_fdm"] = (df["fdm_fit"] * FIT_WEIGHTS["fdm_fit"]).round(2)
    df["contrib_fit_material"] = (
        df["material_fit"] * FIT_WEIGHTS["material_fit"]
    ).round(2)
    df["contrib_fit_clarity"] = (
        df["customer_clarity"] * FIT_WEIGHTS["customer_clarity"]
    ).round(2)
    df["contrib_fit_support"] = (
        df["support_burden"] * FIT_WEIGHTS["support_burden"]
    ).round(2)
    df["fit_score"] = fit_score.round(1)

    # --- Opportunity + Priority --------------------------------------------
    ratio_raw = df["demand_score"] / (
        df["competition_score"] + OPPORTUNITY_COMPETITION_FLOOR
    )
    ratio_norm = normalize(ratio_raw)
    whitespace = df["demand_score"] * (1.0 - df["competition_score"] / 100.0)
    whitespace_norm = normalize(whitespace)
    df["opportunity_raw_ratio"] = ratio_raw.round(4)
    df["opportunity_score"] = (
        ratio_norm * OPPORTUNITY_RATIO_BLEND
        + whitespace_norm * (1.0 - OPPORTUNITY_RATIO_BLEND)
    ).round(1)

    # Priority balances market opportunity with stage-fit
    df["priority_score"] = (
        df["opportunity_score"]
        * (PRIORITY_FIT_FLOOR + (1.0 - PRIORITY_FIT_FLOOR) * df["fit_score"] / 100.0)
    ).round(1)

    df = df.sort_values(
        ["priority_score", "opportunity_score", "demand_score"],
        ascending=[False, False, False],
    )
    df.insert(0, "rank", range(1, len(df) + 1))

    def explain(row: pd.Series) -> str:
        parts = [
            f"priority={row['priority_score']:.0f}",
            f"demand={row['demand_score']:.0f}",
            f"fit={row['fit_score']:.0f}",
            f"comp={row['competition_score']:.0f}",
            f"opp={row['opportunity_score']:.0f}",
        ]
        d_bits = []
        for key in (
            "volume_quality",
            "intent",
            "specificity",
            "problem_intensity",
            "community_downloads",
            "community_makes",
        ):
            c = row.get(f"contrib_demand_{key}", 0) or 0
            if c >= 2.5:
                d_bits.append(f"{key}={c:.0f}")
        if d_bits:
            parts.append("d[" + ", ".join(d_bits[:5]) + "]")
        parts.append(f"fit_flags={row.get('fit_flags', '')}")
        return " | ".join(parts)

    df["score_explanation"] = df.apply(explain, axis=1)

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    df.to_csv(out_path, index=False)

    # Run metadata for Sheets export / Dashboard (sources active, blank-vs-zero)
    run_ts = datetime.now().astimezone()
    run_meta = {
        "run_id": run_ts.isoformat(timespec="seconds"),
        "run_date": run_ts.date().isoformat(),
        "run_time": run_ts.strftime("%H:%M:%S%z"),
        "run_timestamp_utc": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "products_tracked": int(len(df)),
        "demand_unused": list(demand_unused),
        "competition_unused": list(comp_unused),
        "sources": {
            "search_volume": "search_volume" not in demand_unused
            and "volume_quality" not in demand_unused,
            "community": "community_downloads" not in demand_unused,
            "trends": "trends_interest" not in demand_unused
            and "momentum" not in demand_unused,
            "x": "x_volume" not in demand_unused,
            "reddit": "reddit_volume" not in demand_unused,
            "marketplace": "marketplace_listings" not in comp_unused,
        },
        "top_priority_score": float(df["priority_score"].iloc[0]) if len(df) else None,
        "demand_report": out_path,
    }
    meta_path = os.path.join(os.path.dirname(out_path) or "out", "run_meta.json")
    with open(meta_path, "w") as f:
        json.dump(run_meta, f, indent=2)
    print(f"Run metadata written to {meta_path}")

    # --- Console -----------------------------------------------------------
    print("\n=== PRIORITY RANKING (Demand quality × Fit × Opportunity) ===\n")
    display = [
        "rank",
        "product",
        "priority_score",
        "demand_score",
        "fit_score",
        "opportunity_score",
        "competition_score",
        "search_volume",
        "total_listings",
    ]
    display = [c for c in display if c in df.columns]
    print(df[display].to_string(index=False))

    print("\n=== TOP 8 — why ===\n")
    for _, row in df.head(8).iterrows():
        print(f"#{int(row['rank'])}  {row['product']}")
        print(f"    {row['score_explanation']}")
        print(
            f"    volume={int(row['search_volume']):,}  "
            f"best_kw={row.get('search_volume_best_keyword') or '—'}  "
            f"spec={row['raw_specificity']:.0f}  intent={row['raw_intent']:.0f}  "
            f"clarity={row['customer_clarity']:.0f}"
        )

    print(f"\nFull report written to {out_path}")
    print(
        "Sort key: priority_score  "
        f"(opportunity × fit, fit_floor={PRIORITY_FIT_FLOOR})"
    )
    if demand_unused:
        print(f"Demand weights dropped (empty): {', '.join(demand_unused)}")
    print(
        "Active demand weights: "
        + ", ".join(
            f"{k}={v:.2f}" for k, v in sorted(demand_w.items(), key=lambda x: -x[1])
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Rank products by priority (demand quality × fit × opportunity)."
    )
    parser.add_argument("--reddit", default="out/reddit_signal.csv")
    parser.add_argument("--trends", default="out/trends_signal.csv")
    parser.add_argument("--marketplace", default="out/marketplace_signal.csv")
    parser.add_argument("--search-volume", default="out/search_volume_signal.csv")
    parser.add_argument("--community", default="out/printables_cults_signal.csv")
    parser.add_argument("--x", default="out/x_signal.csv")
    parser.add_argument(
        "--products-config",
        default=DEFAULT_PRODUCTS_CONFIG,
        help="products.yaml for keywords + optional fit overrides",
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
        products_config=args.products_config,
    )
