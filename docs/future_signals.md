# Future Demand Signals — Integration Plan & Roadmap

**Status:** Planning / not yet implemented  
**Created:** 2026-08-10  
**Owner:** Project (Grok + Claude)  
**Location:** This file lives in `docs/` so it is easy to find and reference later.

Goal: strengthen the demand monitor with high-signal near-term transaction data and better long-term / sustained interest signals, while preserving the existing **quality-first scoring philosophy**, soft-fail behavior, weight redistribution, and Sheets Dashboard patterns.

All new scanners should follow the same contract as the recent YouTube integration:
- Soft-fail if key/credentials missing or API fails (zeros + notes, exit 0)
- Weekly cache under `cache/`
- `--estimate` / `--smoke` flags
- Output a clean `out/*_signal.csv`
- Update `run_meta.sources.*`
- Blank (not zero) on skip in Sheets export
- Small weights that redistribute when the source is empty

---

## Priority order (recommended implementation sequence)

1. **eBay Sold / Completed Listings** — highest near-term ROI  
2. **Etsy demand / sold proxies** — closest marketplace to pure 3D-print buyers  
3. **Expanded maker platforms** (MakerWorld + Thangs velocity) — deepens the existing community signal  
4. Later backlog (Pinterest Trends, Amazon review mining, TikTok/Reels, etc.)

---

## 1. eBay Sold Listings (Priority 1 — Near-term)

### Why
Actual completed sales + sold prices + sell-through velocity are the strongest proof that people are paying money for a category of part. Extremely valuable for replacement / functional parts ("discontinued", "OEM no longer available", bash guards, mounts, clips, etc.).

### Suggested scanner: `ebay_sold_scan.py`

**Keyword strategy** (same fallback style as YouTube):
```
ebay_keywords → keywords → search_volume_keywords
(max 2–3 per product)
```
Prefer specific phrases that include platform/brand + part type when available.

**Output CSV:** `out/ebay_sold_signal.csv`

| Column | Type | Notes |
|--------|------|-------|
| product | str | join key |
| ebay_sold_count_30d | int | completed sales in last ~30 days |
| ebay_sold_count_90d | int | longer window |
| ebay_avg_sold_price | float | mean sold price (USD) |
| ebay_median_sold_price | float | |
| ebay_min_sold_price | float | |
| ebay_max_sold_price | float | |
| ebay_sell_through_proxy | float | sold / (sold + active) if available, else 0 |
| ebay_top_title | str | highest-sold or most recent relevant title |
| ebay_notes | str | soft-fail reason, cache hit, etc. |
| fetched_at | ISO | |

**Data sources (practical options in 2026):**
- Third-party sold-listings APIs (SoldComps, OpenWeb Ninja, Anysite, Trawl, etc.) — preferred for reliability
- Official eBay Marketplace Insights is restricted; treat as optional later
- Soft-fail cleanly if no `EBAY_SOLD_API_KEY` (or equivalent)

**Cache:** `cache/ebay_sold_cache.json` (weekly TTL)

### Scoring integration (`score_demand.py`)

Add two small demand weights (carve from existing community / X / trends / Reddit / YouTube pool so total still sums to ~1.0):

```python
"ebay_sold_volume": 0.04,      # normalized sold_count_30d (log-scaled + specificity dampening)
"ebay_price_signal": 0.015,    # optional light boost when avg sold price is in a sensible band for FDM parts
```

Rules of thumb:
- Apply the same **specificity dampening** used for community downloads (generic viral mounts should not dominate).
- Empty eBay signal → drop both weights and redistribute.
- Treat very high sold volume of *broad* generic items carefully (same philosophy as volume_quality).

**Competition note:** High active listing counts on eBay can later feed a light competition signal, but start with sold data only.

### Wiring checklist
- [ ] `run_all.sh` — new step + `SKIP_EBAY=1`
- [ ] `.env.example` — `EBAY_SOLD_API_KEY=...`
- [ ] `score_demand.py` — weights + numeric ensure + empty-source redistribution + `run_meta.sources.ebay`
- [ ] `export_to_sheets.py` — Dashboard source chip + blank-on-skip columns on Product Rankings / Scoring Detail
- [ ] `README.md` + `config/products.yaml` header for optional `ebay_keywords`

---

## 2. Etsy Demand / Sold Proxies (Priority 2 — Near-term)

### Why
Etsy is one of the closest marketplaces to people actually buying 3D-printed functional and decorative parts. Search volume + sold counts + "people also bought" style signals are high-value.

### Suggested scanner: `etsy_scan.py`

**Keyword strategy:** same fallback chain, max 2 per product. Prefer `etsy_keywords` override when present.

**Output CSV:** `out/etsy_signal.csv`

| Column | Type | Notes |
|--------|------|-------|
| product | str | |
| etsy_listing_count | int | active listings matching keywords |
| etsy_sold_proxy | int / float | best available sold or "sales" signal (tool-dependent) |
| etsy_avg_price | float | |
| etsy_favorites_proxy | int | if available |
| etsy_top_listing_title | str | |
| etsy_notes | str | |
| fetched_at | ISO | |

**Data options:**
- Free/cheap tiers of eRank, Alura, EverBee, or similar (export or API)
- Careful, rate-limited scraping as a fallback (document fragility)
- Soft-fail if no credentials / tool unavailable

**Cache:** `cache/etsy_cache.json`

### Scoring integration

```python
"etsy_sold_volume": 0.03,
"etsy_listing_saturation": 0.01,   # light competition contribution (or fold into existing marketplace)
```

Keep weights small. Prefer sold/engagement over pure listing count so we don't double-count competition already covered by Printables/Cults + marketplace_scan.

### Wiring checklist
Same pattern as eBay: `SKIP_ETSY=1`, env key, run_meta, blank-on-skip, Dashboard chip, optional `etsy_keywords` in products.yaml.

---

## 3. Expanded Maker Platforms (Priority 3 — Near + Long-term)

### Why
Current community signal is Printables + Cults. Adding **MakerWorld** (strong Bambu ecosystem, high traffic) and **Thangs** (geometric / functional search) improves coverage of what people are actually downloading and making.

### Approach options

**A. Extend existing `printables_cults_scan.py`** (preferred short-term)  
Rename conceptually to a broader community scanner or keep the file and add sources inside it so `out/printables_cults_signal.csv` (or a new `out/community_signal.csv`) gains columns:

- `makerworld_downloads` / `makerworld_makes` / `makerworld_likes`
- `thangs_downloads` or equivalent engagement proxy
- Keep aggregated `community_downloads`, `community_makes`, `community_likes` as the summed/weighted total so `score_demand.py` needs minimal change.

**B. Separate scanners** only if the sites diverge too much in HTML/API shape.

### Scoring impact
Mostly improves the *quality* of the existing community weights rather than adding brand-new large weights. Optionally give MakerWorld a slight emphasis for Bambu-centric products later.

### Wiring
- Update marketplace / community tab in Sheets
- Dashboard chip can stay "Community" or become "Community (Printables/Cults/MakerWorld/Thangs)"
- Soft-fail per-source inside the scanner so one site being down doesn't kill the whole community signal

---

## Suggested weight philosophy (after all three)

Keep total demand weights ≈ 1.0. New commercial/transaction signals stay small so quality dimensions (intent, specificity, problem intensity, volume_quality) remain dominant.

Example target band after eBay + Etsy + YouTube:

| Factor                        | Approx weight |
|-------------------------------|---------------|
| volume_quality                | 0.20–0.22     |
| intent / specificity / problem| ~0.40 combined|
| community_* (downloads/makes/likes) | 0.18–0.20 |
| ebay_sold_volume              | 0.04          |
| etsy_sold_volume              | 0.03          |
| youtube_volume + engagement   | 0.05          |
| trends / momentum / X / Reddit| remainder     |

Empty any optional source → redistribute exactly as today.

---

## Sheets / Dashboard impact

- New source chips on Dashboard status strip: `eBay`, `Etsy` (and expanded Community if needed)
- Product Rankings / Scoring Detail: add the new numeric columns (blank when skipped)
- History: optionally append `ebay_sold_count_30d` and `etsy_sold_proxy` later if we want trend lines on transaction signals (not required for v1 of each scanner)
- Action This Week rules stay the same; stronger near-term data should simply improve the priority scores that feed those rules

---

## Longer-term backlog (not prioritized yet)

| Signal                    | Horizon     | Notes |
|---------------------------|-------------|-------|
| Pinterest Trends          | Leading     | Free, strong early purchase-intent, visual niches |
| Amazon review mining + autocomplete | Near + problem discovery | 1-star "this broke / they changed the design" is pure replacement-part gold |
| TikTok / Reels hashtag & view velocity | Near momentum | Pair with existing YouTube |
| Obsolescence language scan (forums + Reddit + search) | Long-term replacement niche | "discontinued", "no longer available", "OEM NLA" |
| Kickstarter / Indiegogo category history | Validation of willingness-to-pay | Secondary filter |
| Exploding Topics-style early trend | Long-term scouting | Free tier useful for new niches |

These can be added as separate markdown sections or issues when we are ready.

---

## Implementation principles (do not break)

1. **Quality-first** — never let raw volume of generic items dominate.
2. **Soft-fail + redistribute** — missing API key or empty result must never invent signal or crash the pipeline.
3. **products.yaml is the spine** — scanners never create phantom products.
4. **Blank vs zero** — skipped sources render blank in Sheets; `run_meta.sources` is authoritative.
5. **Small weights first** — tune upward only after real weekly runs show the signal is trustworthy.
6. **Cache everything metered** — weekly cadence, respect free/paid quotas.
7. **Document in this file** — when a signal moves from "planned" to "implemented", update its status and link the PR/commit.

---

## Next concrete steps

When ready to implement:

1. Start with **eBay sold** (highest decision value for functional/replacement parts).
2. Mirror the YouTube scanner structure exactly (`--estimate`, `--smoke`, cache, soft-fail, run_meta).
3. After one clean weekly run with real data, decide whether to raise or lower the 0.04 weight.
4. Then Etsy, then deepen the community scanner.

Reference this file in future Claude/Grok prompts as:
`See docs/future_signals.md for the agreed eBay / Etsy / maker-platform plan.`
