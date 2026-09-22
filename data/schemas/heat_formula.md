# Interim heat formula (v1)

Lightweight heat until full scored cadence / `priority_score` returns. **Do not** invent a full ProductScore from heat alone.

```
heat = clamp(0..100, round(
  40 * log1p(evidence_7d)
  + 25 * source_diversity
  + 20 * recency_boost
  − 15 * competition_proxy
))
```

| Term | Meaning |
| --- | --- |
| `evidence_7d` | Count of supporting demand/review signals in the last 7 days (integer ≥0). |
| `source_diversity` | Fraction or count-normalized diversity of distinct sources contributing (0..1 preferred). |
| `recency_boost` | 0..1 boost when evidence is fresh (recent days weighted higher). |
| `competition_proxy` | **0..1** from Etsy/MakerWorld density for the same pain/SKU neighborhood (higher = more crowded competition). |

## Emit path

Optional scored companion CSV (not a ProductScore substitute):

`data/scored/heat_YYYY-MM-DD.csv`

Columns: `product_key,heat,evidence_7d,source_diversity,recency_boost,competition_proxy,run_id,ts`

Also acceptable as additive columns on scored runs: `heat_score`, `heat_formula_version=v1` until full `priority_score` returns.
