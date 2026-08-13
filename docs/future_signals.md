# Future Demand Signals — Integration Plan & Roadmap

**Status:** Active roadmap (eBay + Etsy + MakerWorld/Thangs community: **implemented**)  
**Created:** 2026-08-10  
**Updated:** 2026-08-12 — MakerWorld + Thangs extended community scanner  
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

**Status: implemented** (2026-08-10) — `ebay_sold_scan.py`, SoldComps provider,
weights `ebay_sold_volume` 0.04 + `ebay_price_signal` 0.015, `SKIP_EBAY=1`,
`run_meta.sources.ebay`, Sheets chip. See README + `.env.example`.

### Why
Actual completed sales + sold prices + sell-through velocity are the strongest proof that people are paying money for a category of part. Extremely valuable for replacement / functional parts ("discontinued", "OEM no longer available", bash guards, mounts, clips, etc.).

### Scanner: `ebay_sold_scan.py`

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

**Cache:** `cache/ebay_sold_cache.json` (default TTL **28 days** so weekly runs reuse results)

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
- [x] `run_all.sh` — new step + `SKIP_EBAY=1`
- [x] `.env.example` — `EBAY_SOLD_API_KEY=...`
- [x] `score_demand.py` — weights + numeric ensure + empty-source redistribution + `run_meta.sources.ebay`
- [x] `export_to_sheets.py` — Dashboard source chip + blank-on-skip columns
- [x] `README.md` + `config/products.yaml` header for optional `ebay_keywords`

---

## 2. Etsy Demand / Sold Proxies (Priority 2 — Near-term)

**Status: implemented** (2026-08-11) — `etsy_scan.py` via Etsy Open API v3
active listings search. Demand: `etsy_engagement_volume` 0.02 (favorites
proxy; not true solds). Competition: `etsy_listing_saturation` 0.05 (listing
density, parallel to marketplace listings). **Deviation:** true public sold
counts are not available from Open API; `etsy_sold_proxy` is 0. `SKIP_ETSY=1`,
`run_meta.sources.etsy`, Sheets chip. See README + `.env.example`.

### Why
Etsy is one of the closest marketplaces to people actually buying 3D-printed functional and decorative parts. Search volume + sold counts + "people also bought" style signals are high-value.

### Scanner: `etsy_scan.py`

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

**Cache:** `cache/etsy_cache.json` (default TTL **28 days**)

### Scoring integration

```python
# demand
"etsy_engagement_volume": 0.02,    # favorites (or sold_proxy if ever non-zero)
# competition (not demand)
"etsy_listing_saturation": 0.05,   # log active listing density — supply crowding
```

Listing density is competition (like Printables/Cults counts), not a demand bonus.
Engagement stays small because favorites are weaker evidence than completed sales.

### Wiring checklist
- [x] `run_all.sh` — step + `SKIP_ETSY=1`
- [x] `.env.example` — `ETSY_API_KEY=keystring:shared_secret`
- [x] `score_demand.py` — weights + redistribute + `run_meta.sources.etsy`
- [x] `export_to_sheets.py` — Dashboard chip + blank-on-skip
- [x] `README.md` + `config/products.yaml` optional `etsy_keywords`

---

## 3. Expanded Maker Platforms (Priority 3 — Near + Long-term)

**Status: implemented** (2026-08-12) — Option A: extended
`printables_cults_scan.py` with MakerWorld (public search API) + Thangs
(best-effort HTML; often Cloudflare 403 → soft zeros + notes).
Aggregates still `community_downloads/makes/likes` so `score_demand.py`
unchanged. Cache: `cache/community_platforms_cache.json` (28d).
Dashboard chip: “Community (Printables/Cults/MakerWorld/Thangs)”.

### Why
Current community signal is Printables + Cults. Adding **MakerWorld** (strong Bambu ecosystem, high traffic) and **Thangs** (geometric / functional search) improves coverage of what people are actually downloading and making.

### Approach chosen: **A** (extend existing scanner)
- New columns: `makerworld_*`, `thangs_*` (downloads/makes/likes + sampled + top)
- Aggregates: `community_*` = sum across all platforms that returned numbers
- Soft-fail per platform; one site down does not null the whole community row
- **Deviation:** Thangs is often Cloudflare-blocked from non-browser clients;
  when blocked, thangs_* are 0 with a note — no invented engagement

### Scoring impact
Mostly improves the *quality* of the existing community weights rather than adding brand-new large weights. Optionally give MakerWorld a slight emphasis for Bambu-centric products later.

### Wiring
- [x] Extended `printables_cults_scan.py` + `--estimate` / `--skip-makerworld` / `--skip-thangs`
- [x] Sheets community blank-on-skip columns include MakerWorld/Thangs
- [x] Dashboard chip label expanded
- [x] `products.yaml` header documents optional `makerworld_keywords` / `thangs_keywords`

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

1. ~~Start with **eBay sold**~~ — done.
2. ~~**Etsy**~~ — done (`etsy_scan.py`; sold_proxy limited by Open API).
3. ~~Deepen community (MakerWorld / Thangs)~~ — done (extend printables_cults_scan).
4. After weekly runs with real keys/data, tune eBay / Etsy / community weights if needed.

Reference this file in future Claude/Grok prompts as:
`See docs/future_signals.md for the agreed eBay / Etsy / maker-platform plan.`
