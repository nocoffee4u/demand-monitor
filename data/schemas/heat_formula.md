# Interim heat formula (v2 — Track A split)

Lightweight heat until full scored cadence / `priority_score` returns. **Do not** invent a full ProductScore from heat alone.

## Split scores (required)

Marketplace / Etsy / MakerWorld counts must **not** inflate opportunity. They feed **competition only**.

| Column | Meaning |
| --- | --- |
| `unmet_demand` | 0..100 — rider hangout / WTB / DIY-workaround / OEM-gap evidence. **Opportunity driver.** |
| `competition_density` | 0..1 — Etsy/MW (and similar) density for the same pain/SKU neighborhood. **Punishes or annotates; never boosts unmet.** |
| `heat` | Convenience rank = `unmet_demand` after competition annotation (see below). Pulse cards sort by `unmet_demand` first; `heat` is backward-compatible. |

### unmet_demand (v2)

Evidence classes (buyer-first):

| Class | Weight | Examples |
| --- | --- | --- |
| `wtb` | **3.0** | "looking for", "anyone sell", OOS frustration, pay-for language |
| `diy_workaround` | **2.0** | homemade fix, print-your-own because OEM missing/bad |
| `oem_gap` | **1.5** | live OEM catalog: no SKU **or** durable OOS for the pain |
| `howto_install` | **0.25** | YT install / accessory roundup / review-with-no-pain (heavily discounted) |

```
evidence_w = 3*wtb + 2*diy_workaround + 1.5*oem_gap + 0.25*howto_install
unmet_demand = clamp(0..100, round(
  35 * log1p(evidence_w)
  + 20 * source_diversity_demand   # demand-role sources only
  + 15 * recency_boost
))
```

**Hard demotion:** if OEM substitute/SKU for the pain is **IN STOCK** and `(wtb + diy_workaround) == 0`, cap `unmet_demand` at **18** and prefer `suggested_next` ∈ {`WATCH`,`DROP?`} (never top Pulse cards).

### competition_density (v2)

```
competition_density = clamp(0..1,
  0.5 * min(1, etsy_count/10)
  + 0.3 * min(1, makerworld_count/10)
  + 0.4 * (1 if oem_in_stock_substitute else 0)
)
```

Etsy/MW are `role=competition` only. They **do not** enter `evidence_w`.

### heat (backward-compatible)

```
heat = clamp(0..100, round(unmet_demand * (1 - 0.35 * competition_density)))
```

So crowded competition **lowers** displayed heat; it never raises unmet.

`heat_formula_version=v2`

## Emit path

`data/scored/heat_YYYY-MM-DD.csv`

Columns (v2):

`product_key,heat,unmet_demand,competition_density,evidence_7d,wtb_count,diy_workaround_count,howto_install_count,oem_gap,oem_in_stock_substitute,source_diversity,recency_boost,competition_proxy,run_id,ts,heat_formula_version`

Notes:

- `competition_proxy` retained (= `competition_density`) for older UI readers.
- `evidence_7d` = demand-role supporting signals in last 7d (**excludes** Etsy/MW competition rows).
- Stitch helper: `tools/stitch_heat_v2.py`.
