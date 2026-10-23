# Scored product CSV (Sheet / UI ingest)

One row per product. Demand Monitor UI Bot expects:

`product, category, priority_score, demand_score, fit_score, h2s_fit, competition_score, opportunity_score, score_explanation, action`

Optional extras (additive, UI may ignore until supported):

`product_key, offer_type, signal_ids, demand_sources, competition_sources, run_id, scored_at`

`action` ∈ `PROTOTYPE | WATCH | NEEDS DATA | DROP? | LOCAL | CLOSEST`

Do not sheet-ingest unscored / config-only rows.
