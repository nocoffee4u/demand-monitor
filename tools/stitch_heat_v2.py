#!/usr/bin/env python3
"""stitch_heat_v2.py — Track A heat split: unmet_demand vs competition_density.

Free-stack only. Does not invent metrics; caller supplies evidence class counts
from hunt signals (buyer hangouts = demand; Etsy/MW = competition).
"""
from __future__ import annotations
import argparse, csv, math, sys
from pathlib import Path

def clamp(x, lo=0.0, hi=100.0):
    return max(lo, min(hi, x))

def unmet_demand(wtb: float, diy: float, oem_gap: float, howto: float,
                 source_diversity: float, recency_boost: float,
                 oem_in_stock_substitute: bool) -> int:
    evidence_w = 3.0 * wtb + 2.0 * diy + 1.5 * oem_gap + 0.25 * howto
    score = 35 * math.log1p(evidence_w) + 20 * source_diversity + 15 * recency_boost
    score = clamp(round(score))
    if oem_in_stock_substitute and (wtb + diy) <= 0:
        score = min(score, 18)
    return int(score)

def competition_density(etsy: float, mw: float, oem_in_stock_substitute: bool) -> float:
    d = 0.5 * min(1.0, etsy / 10.0) + 0.3 * min(1.0, mw / 10.0)
    if oem_in_stock_substitute:
        d += 0.4
    return round(clamp(d, 0.0, 1.0), 2)

def heat_from(unmet: int, comp: float) -> int:
    return int(clamp(round(unmet * (1.0 - 0.35 * comp))))

def row_score(r: dict) -> dict:
    wtb = float(r.get("wtb_count") or 0)
    diy = float(r.get("diy_workaround_count") or 0)
    howto = float(r.get("howto_install_count") or 0)
    oem_gap = float(r.get("oem_gap") or 0)
    sd = float(r.get("source_diversity") or 0)
    rb = float(r.get("recency_boost") or 0)
    etsy = float(r.get("etsy_count") or 0)
    mw = float(r.get("makerworld_count") or 0)
    oem_stock = str(r.get("oem_in_stock_substitute") or "").lower() in ("1", "true", "yes")
    unmet = unmet_demand(wtb, diy, oem_gap, howto, sd, rb, oem_stock)
    comp = competition_density(etsy, mw, oem_stock)
    heat = heat_from(unmet, comp)
    out = dict(r)
    out.update({
        "unmet_demand": unmet,
        "competition_density": comp,
        "competition_proxy": comp,
        "heat": heat,
        "oem_in_stock_substitute": "true" if oem_stock else "false",
        "heat_formula_version": "v2",
    })
    return out

HEAT_COLS = [
    "product_key","heat","unmet_demand","competition_density","evidence_7d",
    "wtb_count","diy_workaround_count","howto_install_count","oem_gap",
    "oem_in_stock_substitute","source_diversity","recency_boost","competition_proxy",
    "run_id","ts","heat_formula_version",
]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True, help="CSV with evidence class counts")
    ap.add_argument("--out", required=True, help="heat CSV out")
    args = ap.parse_args()
    rows = list(csv.DictReader(Path(args.inp).open()))
    scored = [row_score(r) for r in rows]
    scored.sort(key=lambda r: (-int(r["unmet_demand"]), -int(r["heat"])))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with Path(args.out).open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HEAT_COLS, extrasaction="ignore")
        w.writeheader()
        for r in scored:
            w.writerow(r)
    print(f"wrote {args.out} n={len(scored)}", file=sys.stderr)

if __name__ == "__main__":
    main()
