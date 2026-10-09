Weekday hunt stitches cross-source pain into opportunity rows for Pulse (`data/opportunities/YYYY-MM-DD.csv`, optional jsonl). `opportunity_id` is stable across days (hash of product_key|normalized_pain). Never invent sales or engagement counts.

Track A (2026-09-23): additive columns `unmet_demand`, `competition_density`, `teardown_status`, `teardown_ref`. Etsy/MW must not inflate unmet. Cards above WATCH require teardown (see `data/schemas/competitive_teardown.md`). `DROP?` demotes OEM-in-stock + thin buyer evidence.
