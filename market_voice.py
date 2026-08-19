#!/usr/bin/env python3
"""
market_voice.py
---------------
Market Voice v1 — rule-based marketing/design language from existing signals.

Inputs (no new scanners):
  - out/demand_report.csv (titles, amazon_suggestions, AC hits, freshness)
  - out/search_volume_keywords.csv (multi-phrase buyer language + volumes)
  - out/run_meta.json (coverage notes)

Outputs:
  - DataFrame / out/market_voice.csv for Sheets "Market Voice" tab

Tier 1 = search volume phrases; Tier 2 = amazon_suggestions (persisted AC
strings, separator " | "); Tier 3 = competitive titles.
top_problem_phrases prefers complaint-filtered Amazon suggestions; if
suggestions exist but none match complaint language, leave empty (honest).
Tier-1 problem filter is fallback only when no Amazon suggestion text.

No NLP; explainable regex tags only. Soft-fail → blank / explicit notes.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

import pandas as pd

VOICE_COLS = [
    "rank",
    "product",
    "category",
    "priority_score",
    "top_intent_phrases",
    "top_problem_phrases",
    "proof_snippets",
    "competitive_titles",
    "design_must_haves",
    "social_hook",
    "confidence",
    "channel_bias",
    "voice_notes",
    "data_as_of",
]

# Must match amazon_scan.SUGGESTIONS_SEP
AMAZON_SUGGESTIONS_SEP = " | "

# Explainable tag vocabulary → regex (Tier 1/2 buyer phrases + titles)
TAG_RULES: list[tuple[str, re.Pattern[str]]] = [
    (
        "replacement",
        re.compile(
            r"\b(replace|replacement|spare|oem\s*nla|no\s*longer\s*available|"
            r"discontinued)\b",
            re.I,
        ),
    ),
    (
        "durability/fit",
        re.compile(
            r"\b(break|broken|crack|fail|failed|loose|rattle|wobble|wear|worn|"
            r"damage|damaged|missing|lost)\b",
            re.I,
        ),
    ),
    (
        "protection",
        re.compile(
            r"\b(cover|cap|guard|protector|dust|fuse|shield|boot)\b",
            re.I,
        ),
    ),
    (
        "compatibility",
        re.compile(
            r"\b(adapter|mount|bracket|holder|clip|hook|fit|compatible|"
            r"widener|extender)\b",
            re.I,
        ),
    ),
    (
        "aftermarket",
        re.compile(
            r"\b(aftermarket|upgrade|better|improved|mod|custom)\b",
            re.I,
        ),
    ),
    (
        "oem_nla",
        re.compile(
            r"\b(oem|nla|discontinued|no\s*longer\s*available|"
            r"out\s*of\s*stock)\b",
            re.I,
        ),
    ),
]

# Competitive-only differentiation cue (seller language, not buyer)
UNIVERSAL_GENERIC = re.compile(r"\b(universal|generic|fits\s+most)\b", re.I)

# Genuine complaint/failure language only — not structural nouns (cover/cap/guard)
# that appear in every product name and fake "problem" hits.
PROBLEM_PHRASE = re.compile(
    r"\b(break|broken|crack|fail|failed|loose|rattle|wobble|wear|worn|"
    r"damage|damaged|missing|lost|discontinued|nla|oem|"
    r"no\s*longer\s*available)\b",
    re.I,
)

# Same spirit as score_demand.BROAD_GENERIC — avoid headlining viral generics.
try:
    from score_demand import BROAD_GENERIC as _BROAD_GENERIC
except ImportError:  # pragma: no cover
    _BROAD_GENERIC = re.compile(
        r"\b(car\s*phone\s*(holder|mount)|phone\s*holder|phone\s*mount|"
        r"bike\s*phone\s*mount|handlebar\s*phone\s*mount|"
        r"dash\s*phone\s*mount|magnetic\s*car\s*mount|"
        r"gopro\s*mount|action\s*camera)\b",
        re.I,
    )
BROAD_GENERIC = _BROAD_GENERIC

# Ultra-generic headlines (full-phrase only — do not match inside
# "dash phone mount" / "magnetic car mount").
VERY_BROAD = re.compile(
    r"^(car\s*phone\s*(holder|mount)|phone\s*(holder|mount)|"
    r"bike\s*phone\s*mount|handlebar\s*phone\s*mount|gopro\s*mount)$",
    re.I,
)

# Match amazon_scan shrinkage spirit: n/4 → full credit at n>=4; caveat only when small
AMAZON_AC_SHRINK_THRESHOLD = 3

COMPETITIVE_TITLE_COLS = [
    ("ebay", "ebay_top_title"),
    ("etsy", "etsy_top_listing_title"),
    ("amazon", "amazon_top_title"),
    ("printables", "printables_top_name"),
    ("cults", "cults_top_name"),
    ("makerworld", "makerworld_top_name"),
    ("thangs", "thangs_top_name"),
]

FRESHNESS_COLS = [
    ("ebay", "ebay_fetched_at"),
    ("etsy", "etsy_fetched_at"),
    ("amazon", "amazon_fetched_at"),
]


def _safe_read(path: str) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(p)
    except Exception:
        return pd.DataFrame()


def _load_meta(path: str = "out/run_meta.json") -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _clean(s: Any) -> str:
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ""
    t = str(s).strip()
    if t.lower() in ("nan", "none", ""):
        return ""
    return t


def tag_texts(texts: list[str]) -> list[str]:
    """Return ordered unique explainable tags matched in any text."""
    blob_list = [t for t in texts if t]
    if not blob_list:
        return []
    found: list[str] = []
    for tag, rx in TAG_RULES:
        if any(rx.search(t) for t in blob_list):
            found.append(tag)
    return found


def phrases_for_product(
    kw_df: pd.DataFrame, product: str, *, limit: int = 5
) -> list[tuple[str, float]]:
    """Top search-volume phrases for a product (volume-ranked)."""
    if kw_df.empty or "product" not in kw_df.columns:
        return []
    sub = kw_df[kw_df["product"].astype(str) == product].copy()
    if sub.empty:
        return []
    if "no_data" in sub.columns:
        sub = sub[~sub["no_data"].astype(str).str.lower().isin(("true", "1"))]
    sub["search_volume"] = pd.to_numeric(sub.get("search_volume"), errors="coerce").fillna(0)
    sub["keyword"] = sub["keyword"].map(_clean)
    sub = sub[sub["keyword"] != ""]
    sub = sub.sort_values("search_volume", ascending=False)
    out: list[tuple[str, float]] = []
    seen: set[str] = set()
    for _, r in sub.iterrows():
        k = r["keyword"]
        if k.lower() in seen:
            continue
        seen.add(k.lower())
        out.append((k, float(r["search_volume"])))
        if len(out) >= limit:
            break
    return out


def competitive_titles_for_row(row: pd.Series) -> list[tuple[str, str]]:
    """(source, title) pairs — seller/maker language, not buyer voice."""
    out: list[tuple[str, str]] = []
    for src, col in COMPETITIVE_TITLE_COLS:
        t = _clean(row.get(col))
        if t:
            out.append((src, t[:160]))
    return out


def channel_bias_for_row(
    row: pd.Series,
    phrases: list[tuple[str, float]],
    titles: list[tuple[str, str]],
) -> str:
    """Where language evidence is strongest this run (heuristic, explainable)."""
    scores: dict[str, float] = {}
    if phrases:
        scores["search"] = float(sum(v for _, v in phrases)) + 10.0 * len(phrases)
    for src, _ in titles:
        scores[src] = scores.get(src, 0.0) + 5.0
    # Light boosts from active numeric signals
    try:
        if float(row.get("amazon_autocomplete_hits") or 0) > 0:
            scores["amazon"] = scores.get("amazon", 0.0) + float(
                row.get("amazon_autocomplete_hits") or 0
            )
    except (TypeError, ValueError):
        pass
    try:
        if float(row.get("ebay_sold_count_30d") or 0) > 0:
            scores["ebay"] = scores.get("ebay", 0.0) + 3.0
    except (TypeError, ValueError):
        pass
    try:
        if float(row.get("youtube_matching_videos") or 0) > 0:
            scores["youtube"] = scores.get("youtube", 0.0) + 2.0
    except (TypeError, ValueError):
        pass
    if not scores:
        return ""
    ranked = sorted(scores.items(), key=lambda x: -x[1])
    return ";".join(s for s, _ in ranked[:3])


def data_as_of_for_row(row: pd.Series) -> str:
    parts: list[str] = []
    for src, col in FRESHNESS_COLS:
        ts = _clean(row.get(col))
        if ts:
            # Keep date portion for readability
            day = ts[:10] if len(ts) >= 10 else ts
            parts.append(f"{src}:{day}")
    return "; ".join(parts)


def parse_amazon_suggestions(row: pd.Series) -> list[str]:
    """Split amazon_suggestions (joined by ' | '). Empty → []."""
    raw = _clean(row.get("amazon_suggestions"))
    if not raw:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for part in raw.split("|"):
        s = part.strip()
        if not s:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def voice_notes_for_row(
    row: pd.Series,
    meta: dict,
    n_phrases: int,
    *,
    hook_skipped_broad: str = "",
    n_amazon_suggestions: int = 0,
    amazon_problem_empty: bool = False,
) -> str:
    notes: list[str] = []
    sources = meta.get("sources") or {}
    if not sources.get("search_volume", True) and n_phrases == 0:
        notes.append("search_volume inactive — no buyer phrases")
    ok = meta.get("community_platforms_ok")
    total = meta.get("community_platforms_total")
    if ok is not None and total is not None:
        try:
            if int(ok) < int(total):
                notes.append(f"community partial {ok}/{total}")
        except (TypeError, ValueError):
            pass
    amz_notes = _clean(row.get("amazon_notes"))
    no_rf = "no_rainforest" in amz_notes.lower() or "ac-only" in amz_notes.lower()
    if n_amazon_suggestions > 0:
        notes.append(f"amazon_suggestions={n_amazon_suggestions}")
        if no_rf:
            # Have real AC text — do not imply "AC with no text"
            notes.append("amazon listing density unavailable (no Rainforest)")
        if amazon_problem_empty:
            notes.append("amazon suggestions present; no complaint-term matches")
    elif no_rf:
        notes.append("amazon AC-only (no listing density)")
    elif not sources.get("amazon", False):
        notes.append("amazon inactive")
    try:
        ac = int(float(row.get("amazon_autocomplete_hits") or 0))
        prob = int(float(row.get("amazon_problem_mention_score") or 0))
        if ac > 0 or prob > 0:
            # Only label "shrunk sample" when n is actually small (n/4 spirit)
            if ac < AMAZON_AC_SHRINK_THRESHOLD:
                notes.append(f"amazon_problem={prob} (n_ac={ac}; shrunk sample)")
            else:
                notes.append(f"amazon_problem={prob} (n_ac={ac})")
    except (TypeError, ValueError):
        pass
    if hook_skipped_broad:
        notes.append(hook_skipped_broad)
    if not sources.get("youtube", True):
        notes.append("youtube inactive — no titles in v1 anyway")
    if (
        n_phrases == 0
        and not competitive_titles_for_row(row)
        and n_amazon_suggestions == 0
    ):
        notes.append("no voice evidence this run")
    return "; ".join(notes)[:400]


def pick_social_hook(
    phrases: list[tuple[str, float]],
    titles: list[tuple[str, str]],
) -> tuple[str, str]:
    """
    Prefer top-volume phrase that is NOT BROAD_GENERIC.
    If every phrase is broad, prefer one that is not VERY_BROAD (e.g. dash /
    magnetic niche over 'car phone holder'). Last resort: absolute top volume.
    Returns (hook, optional note when absolute top volume was skipped as generic).
    """
    if not phrases:
        if titles:
            src, title = titles[0]
            return f"[{src} listing] {title[:80]}", ""
        return "no voice evidence", ""

    top_p, top_v = phrases[0]
    chosen: tuple[str, float] | None = None
    for p, v in phrases:
        if BROAD_GENERIC.search(p):
            continue
        chosen = (p, v)
        break

    if chosen is None:
        # All BROAD_GENERIC — prefer a less ultra-generic niche phrase
        for p, v in phrases:
            if VERY_BROAD.search(p):
                continue
            chosen = (p, v)
            break

    if chosen is None:
        # Nothing better — absolute top volume, but flag it
        return (
            f"'{top_p}' — real search phrase, {int(top_v)}/mo",
            f"hook is broad-generic '{top_p}' ({int(top_v)}/mo); no specific phrase",
        )

    hook_p, hook_v = chosen
    hook = f"'{hook_p}' — real search phrase, {int(hook_v)}/mo"
    skipped_note = ""
    if (BROAD_GENERIC.search(top_p) or VERY_BROAD.search(top_p)) and (
        top_p.lower() != hook_p.lower()
    ):
        skipped_note = f"hook skipped broad '{top_p}' ({int(top_v)}/mo)"
    return hook, skipped_note


def confidence_label(n_phrases: int, n_titles: int) -> str:
    n = n_phrases + n_titles
    if n <= 0:
        return "n=0 — no evidence"
    if n_phrases <= 1 and n_titles <= 1:
        return f"n={n_phrases} phrase(s), {n_titles} title(s) — low confidence"
    if n_phrases < 3:
        return f"n={n_phrases} phrases — medium confidence"
    return f"n={n_phrases} phrases — ok confidence"


def build_market_voice(
    report: pd.DataFrame | None = None,
    keywords: pd.DataFrame | None = None,
    meta: dict | None = None,
    *,
    report_path: str = "out/demand_report.csv",
    keywords_path: str = "out/search_volume_keywords.csv",
    meta_path: str = "out/run_meta.json",
    max_intent: int = 5,
    max_problem: int = 3,
    max_titles: int = 3,
) -> pd.DataFrame:
    """
    One row per product, sorted by priority_score (desc).
    Soft-fail: missing inputs → empty frame with correct columns.
    """
    if report is None:
        report = _safe_read(report_path)
    if keywords is None:
        keywords = _safe_read(keywords_path)
    if meta is None:
        meta = _load_meta(meta_path)

    if report is None or report.empty or "product" not in report.columns:
        return pd.DataFrame(columns=VOICE_COLS)

    df = report.copy()
    if "priority_score" in df.columns:
        df = df.sort_values("priority_score", ascending=False)
    elif "rank" in df.columns:
        df = df.sort_values("rank", ascending=True)

    rows: list[dict] = []
    for _, row in df.iterrows():
        product = _clean(row.get("product"))
        if not product:
            continue
        phrases = phrases_for_product(keywords, product, limit=max_intent)
        titles = competitive_titles_for_row(row)[:max_titles]

        intent_strs = [f"{p} ({int(v)}/mo)" if v else p for p, v in phrases]
        amz_sugg = parse_amazon_suggestions(row)
        amz_complaint = [s for s in amz_sugg if PROBLEM_PHRASE.search(s)]
        if amz_sugg:
            # Prefer Amazon AC text; empty when none match complaint language
            problem_phrases = amz_complaint[:max_problem]
            amazon_problem_empty = len(amz_complaint) == 0
        else:
            # No AC text — Tier-1 search phrases only if useful
            problem_phrases = [
                p for p, _ in phrases if PROBLEM_PHRASE.search(p)
            ][:max_problem]
            amazon_problem_empty = False

        # 1–2 [amazon] proof snippets (complaint matches first, else any sample)
        proof_src = amz_complaint[:2] if amz_complaint else amz_sugg[:2]
        proof_snippets = " | ".join(f"[amazon] {s}" for s in proof_src)

        buyer_texts = [p for p, _ in phrases] + amz_sugg
        title_texts = [t for _, t in titles]
        must = tag_texts(buyer_texts)
        # Differentiation: universal/generic in competitive titles but not buyer phrases
        buyer_blob = " ".join(buyer_texts).lower()
        if any(UNIVERSAL_GENERIC.search(t) for t in title_texts):
            if not UNIVERSAL_GENERIC.search(buyer_blob):
                must.append("differentiation_opportunity")

        hook, hook_skipped = pick_social_hook(phrases, titles)
        comp = " | ".join(f"[{s}] {t}" for s, t in titles)

        rows.append(
            {
                "rank": row.get("rank", ""),
                "product": product,
                "category": _clean(row.get("category")),
                "priority_score": row.get("priority_score", ""),
                "top_intent_phrases": "; ".join(intent_strs),
                "top_problem_phrases": "; ".join(problem_phrases),
                "proof_snippets": proof_snippets,
                "competitive_titles": comp,
                "design_must_haves": "; ".join(must),
                "social_hook": hook,
                "confidence": confidence_label(len(phrases), len(titles)),
                "channel_bias": channel_bias_for_row(row, phrases, titles),
                "voice_notes": voice_notes_for_row(
                    row,
                    meta,
                    len(phrases),
                    hook_skipped_broad=hook_skipped,
                    n_amazon_suggestions=len(amz_sugg),
                    amazon_problem_empty=amazon_problem_empty,
                ),
                "data_as_of": data_as_of_for_row(row),
            }
        )

    out = pd.DataFrame(rows, columns=VOICE_COLS)
    return out


def write_market_voice(df: pd.DataFrame, path: str = "out/market_voice.csv") -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    df.to_csv(path, index=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build Market Voice table (v1).")
    parser.add_argument("--report", default="out/demand_report.csv")
    parser.add_argument("--keywords", default="out/search_volume_keywords.csv")
    parser.add_argument("--meta", default="out/run_meta.json")
    parser.add_argument("--out", default="out/market_voice.csv")
    args = parser.parse_args()
    voice = build_market_voice(
        report_path=args.report,
        keywords_path=args.keywords,
        meta_path=args.meta,
    )
    write_market_voice(voice, args.out)
    print(f"Wrote {len(voice)} rows → {args.out}")
    if not voice.empty:
        print(voice.head(3).to_string(index=False))
